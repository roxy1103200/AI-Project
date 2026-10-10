package com.cinema.ticketing.service;

import com.cinema.ticketing.config.SalesReportSchemaInitializer;
import com.cinema.ticketing.dto.ReportFilter;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import com.cinema.ticketing.mq.OrderMessagePublisher;
import com.cinema.ticketing.common.BusinessException;
import java.time.LocalDateTime;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import java.math.BigDecimal;
import java.time.LocalDate;
import static org.junit.jupiter.api.Assertions.*;

/** Temporary tables shadow application tables on this one connection; no business rows are changed. */
@EnabledIfSystemProperty(named = "report.mysql", matches = "true")
class ReportMysqlCompatibilityTest {
    @Test
    void nativeQueriesAndTimestampMigrationAreIndependentOfSessionTimezone() throws Exception {
        String url = System.getenv().getOrDefault("DB_URL", "jdbc:mysql://127.0.0.1:3306/cinema_ticketing?serverTimezone=UTC&useSSL=false&allowPublicKeyRetrieval=true&connectTimeout=3000");
        var source = new DriverManagerDataSource(url, System.getenv().getOrDefault("DB_USERNAME", "cinema"),
                System.getenv().getOrDefault("DB_PASSWORD", "cinema"));
        try (var connection = source.getConnection()) {
            var shared = new SingleConnectionDataSource(connection, true);
            var jdbc = new JdbcTemplate(shared);
            SalesReportIntegrationTest.fixtures(jdbc, true);
            // 16:30 UTC on October 10 belongs to October 11 in Beijing.
            jdbc.execute("SET time_zone='+00:00'");
            jdbc.update("UPDATE refund_record SET refunded_at=NULL,created_at=FROM_UNIXTIME(?)", 1791649800L);
            jdbc.execute(SalesReportSchemaInitializer.NORMALIZE_REFUND_TIME_SQL);
            String normalized = jdbc.queryForObject("SELECT CAST(refunded_at AS CHAR) FROM refund_record", String.class);
            assertEquals("2026-10-11 00:30:00", normalized);
            jdbc.execute("SET time_zone='+08:00'");
            jdbc.update("UPDATE refund_record SET refunded_at=NULL");
            jdbc.execute(SalesReportSchemaInitializer.NORMALIZE_REFUND_TIME_SQL);
            assertEquals(normalized, jdbc.queryForObject("SELECT CAST(refunded_at AS CHAR) FROM refund_record", String.class));
            var filter = new ReportFilter(LocalDate.of(2026, 10, 9), LocalDate.of(2026, 10, 11), null, null);
            var report = new SalesReportService(jdbc).sales(filter);
            assertEquals(new BigDecimal("180.20"), report.summary().paidAmount());
            assertEquals(new BigDecimal("80.00"), report.summary().refundAmount());
            assertEquals(4, report.summary().grossTicketCount());
            var occupancy = new OccupancyReportService(jdbc).occupancy(filter);
            assertEquals(2, occupancy.summary().effectiveTicketCount());
            assertEquals(1, occupancy.summary().unknownCapacityScreenings());
            String export = new String(new ReportExportService(jdbc, new OccupancyReportService(jdbc)).sales(filter), java.nio.charset.StandardCharsets.UTF_8);
            assertEquals(4, export.lines().count());
            jdbc.execute("CREATE INDEX idx_payment_report_time ON payment_transaction(status,paid_at,order_id)");
            var plan = jdbc.queryForList("EXPLAIN SELECT amount FROM payment_transaction WHERE status='SUCCESS' AND paid_at>='2026-10-09' AND paid_at<'2026-10-12'");
            assertTrue(plan.getFirst().get("possible_keys").toString().contains("idx_payment_report_time"));

            // Exercise the actual seat-lock SQL and rollback boundary with isolated Redis responses.
            jdbc.execute("ALTER TABLE screening ADD COLUMN price DECIMAL(10,2) DEFAULT 40.00");
            jdbc.execute("ALTER TABLE movie ADD COLUMN sale_start_time DATETIME NULL, ADD COLUMN sale_end_time DATETIME NULL");
            jdbc.execute("ALTER TABLE order_item ADD COLUMN seat_id BIGINT NULL");
            jdbc.update("INSERT INTO screening(id,movie_id,hall_id,start_time,end_time,status,price) VALUES(4,2,2,?,?,'SCHEDULED',40.00)",
                    LocalDateTime.now().plusDays(1), LocalDateTime.now().plusDays(1).plusHours(2));
            jdbc.update("INSERT INTO seat VALUES(10,2,'AVAILABLE'),(11,2,'AVAILABLE'),(12,2,'DISABLED')");
            var redis = mock(StringRedisTemplate.class);
            when(redis.execute(any(org.springframework.data.redis.core.script.RedisScript.class), anyList(), any(Object[].class)))
                    .thenReturn(0L, 1L);
            var orders = new OrderService(jdbc, redis, mock(OrderMessagePublisher.class));
            var transaction = new TransactionTemplate(new DataSourceTransactionManager(shared));
            assertThrows(BusinessException.class, () -> transaction.execute(status -> orders.lockSeats("owner", 4, List.of(10L))));
            assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM screening_capacity_snapshot WHERE screening_id=4", Integer.class));
            transaction.execute(status -> orders.lockSeats("owner", 4, List.of(10L)));
            assertEquals(2, jdbc.queryForObject("SELECT sellable_seat_count FROM screening_capacity_snapshot WHERE screening_id=4", Integer.class));
        }
    }
}
