package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.GlobalExceptionHandler;
import com.cinema.ticketing.controller.SalesReportController;
import com.cinema.ticketing.config.SalesReportSchemaInitializer;
import com.cinema.ticketing.dto.ReportFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** Real SQL with isolated data; deliberately includes multiseat orders, refunds and disabled catalog entries. */
class SalesReportIntegrationTest {
    private JdbcTemplate jdbc;
    private SalesReportService sales;
    private OccupancyReportService occupancy;
    private ReportExportService exports;
    private MockMvc mvc;
    private static final LocalDate DAY = LocalDate.of(2026, 10, 10);

    @BeforeEach
    void setup() {
        jdbc = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:" + UUID.randomUUID()
                + ";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1", "sa", ""));
        fixtures(jdbc, false);
        sales = new SalesReportService(jdbc);
        occupancy = new OccupancyReportService(jdbc);
        exports = new ReportExportService(jdbc, occupancy);
        AuthService auth = mock(AuthService.class);
        doThrow(new BusinessException(403, "需要管理员权限")).when(auth).requireAdmin("user");
        mvc = MockMvcBuilders.standaloneSetup(new SalesReportController(auth, sales, occupancy, exports))
                .setControllerAdvice(new GlobalExceptionHandler()).build();
    }

    static void fixtures(JdbcTemplate jdbc, boolean temporary) {
        String create = temporary ? "CREATE TEMPORARY TABLE " : "CREATE TABLE ";
        for (String ddl : List.of(
                "cinema(id BIGINT PRIMARY KEY,name VARCHAR(120),status VARCHAR(20))",
                "movie(id BIGINT PRIMARY KEY,title VARCHAR(120),status VARCHAR(20))",
                "hall(id BIGINT PRIMARY KEY,cinema_id BIGINT,name VARCHAR(120),row_count INT,column_count INT,status VARCHAR(20))",
                "screening(id BIGINT PRIMARY KEY,movie_id BIGINT,hall_id BIGINT,start_time DATETIME,end_time DATETIME,status VARCHAR(20))",
                "seat(id BIGINT PRIMARY KEY,hall_id BIGINT,status VARCHAR(20))",
                "ticket_order(id BIGINT PRIMARY KEY,order_no VARCHAR(64),screening_id BIGINT,status VARCHAR(20))",
                "order_item(id BIGINT PRIMARY KEY,order_id BIGINT,ticket_status VARCHAR(20),checked_in_at DATETIME)",
                "payment_transaction(id BIGINT PRIMARY KEY,order_id BIGINT,amount DECIMAL(10,2),status VARCHAR(20),paid_at DATETIME,payment_no VARCHAR(100))",
                "refund_record(id BIGINT PRIMARY KEY,order_id BIGINT,amount DECIMAL(10,2),status VARCHAR(20),refunded_at DATETIME,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
                "screening_capacity_snapshot(screening_id BIGINT PRIMARY KEY,sellable_seat_count INT,captured_at DATETIME)")) jdbc.execute(create + ddl);
        jdbc.update("INSERT INTO cinema VALUES(1,'停用影院','INACTIVE'),(2,'影院二','ACTIVE')");
        jdbc.update("INSERT INTO movie VALUES(1,'停售影片','OFFLINE'),(2,'影片二','ON_SHELF')");
        jdbc.update("INSERT INTO hall VALUES(1,1,'一号厅',2,2,'ACTIVE'),(2,2,'二号厅',2,2,'ACTIVE')");
        jdbc.update("INSERT INTO screening VALUES(1,1,1,'2026-10-10 23:30:00','2026-10-11 01:30:00','SCHEDULED'),"
                + "(2,2,2,'2026-10-10 10:00:00','2026-10-10 12:00:00','SCHEDULED'),"
                + "(3,1,1,'2026-10-10 10:00:00','2026-10-10 12:00:00','CANCELLED')");
        jdbc.update("INSERT INTO ticket_order VALUES(1,'O1',1,'ISSUED'),(2,'O2',1,'REFUNDED'),(3,'O3',2,'UNPAID'),(4,'O4',1,'CANCELLED')");
        jdbc.update("INSERT INTO order_item VALUES(1,1,'ISSUED','2026-10-10 23:20:00'),(2,1,'VALID',NULL),"
                + "(3,2,'REFUNDED',NULL),(4,2,'REFUNDED',NULL),(5,3,'VALID',NULL),(6,4,'CANCELLED',NULL)");
        jdbc.update("INSERT INTO payment_transaction VALUES(1,1,100.20,'SUCCESS','2026-10-09 23:59:59','DEMO-1'),"
                + "(2,2,80.00,'SUCCESS','2026-10-10 00:00:00','DEMO-2'),"
                + "(3,4,99.00,'FAILED','2026-10-10 10:00:00','FAIL')");
        jdbc.update("INSERT INTO refund_record(id,order_id,amount,status,refunded_at) VALUES(1,2,80.00,'REFUNDED','2026-10-11 00:00:00')");
        jdbc.update("INSERT INTO screening_capacity_snapshot VALUES(1,4,'2026-10-01 12:00:00'),(3,4,'2026-10-01 12:00:00')");
    }

    private ReportFilter filter(LocalDate from, LocalDate to) { return new ReportFilter(from, to, null, null); }

    @Test
    void monetaryFactsAreCountedOnceAndRefundsBelongToRefundDate() {
        var paidDay = sales.sales(filter(DAY, DAY));
        assertEquals(new BigDecimal("80.00"), paidDay.summary().paidAmount());
        assertEquals(new BigDecimal("0.00"), paidDay.summary().refundAmount());
        assertEquals(2, paidDay.summary().grossTicketCount());
        var refundDay = sales.sales(filter(DAY.plusDays(1), DAY.plusDays(1)));
        assertEquals(new BigDecimal("80.00"), refundDay.summary().refundAmount());
        assertEquals(new BigDecimal("-80.00"), refundDay.summary().netAmount());
        var whole = sales.sales(filter(DAY.minusDays(1), DAY.plusDays(1)));
        assertEquals(new BigDecimal("180.20"), whole.summary().paidAmount());
        assertEquals(4, whole.summary().grossTicketCount());
        assertEquals(3, whole.items().size());
    }

    @Test
    void optionalDimensionsAndEmptyRangesDoNotExcludeHistoricalInactiveCatalog() {
        assertEquals(new BigDecimal("80.00"), sales.sales(new ReportFilter(DAY, DAY, 1L, 1L)).summary().paidAmount());
        assertTrue(sales.sales(new ReportFilter(DAY, DAY, 2L, null)).items().isEmpty());
        assertEquals(new BigDecimal("0.00"), sales.sales(filter(DAY.minusDays(5), DAY.minusDays(5))).summary().paidAmount());
    }

    @Test
    void occupancyCountsPaidValidItemsIncludingCheckedInAndPreservesUnknownHistoricalCapacity() {
        var report = occupancy.occupancy(filter(DAY, DAY));
        assertEquals(2, report.summary().screeningCount());
        assertEquals(2, report.summary().effectiveTicketCount());
        assertEquals(1, report.summary().unknownCapacityScreenings());
        assertNull(report.summary().occupancyRate());
        var known = report.items().stream().filter(row -> row.screeningId() == 1).findFirst().orElseThrow();
        assertEquals(new BigDecimal("0.500000"), known.occupancyRate());
        assertEquals(2, known.effectiveTicketCount());
        assertEquals(1, report.popular().getFirst().screeningId());
        jdbc.update("INSERT INTO screening_capacity_snapshot VALUES(2,6,'2026-10-01 12:00:00')");
        assertEquals(new BigDecimal("0.200000"), occupancy.occupancy(filter(DAY, DAY)).summary().occupancyRate());
        assertEquals(0, occupancy.occupancy(filter(DAY.plusDays(1), DAY.plusDays(1))).summary().screeningCount());
    }

    @Test
    void capacitySnapshotUsesSellableSeatsOnceAndLegacyOrdersRemainUnknown() {
        jdbc.update("INSERT INTO screening VALUES(4,1,1,?,?, 'SCHEDULED')", LocalDateTime.now().plusDays(1), LocalDateTime.now().plusDays(1).plusHours(2));
        jdbc.update("INSERT INTO seat VALUES(1,1,'AVAILABLE'),(2,1,'AVAILABLE'),(3,1,'DISABLED')");
        ScreeningCapacity.capture(jdbc, 4, 1);
        assertEquals(2, jdbc.queryForObject("SELECT sellable_seat_count FROM screening_capacity_snapshot WHERE screening_id=4", Integer.class));
        jdbc.update("UPDATE seat SET status='AVAILABLE' WHERE id=3");
        ScreeningCapacity.capture(jdbc, 4, 1);
        assertEquals(2, jdbc.queryForObject("SELECT sellable_seat_count FROM screening_capacity_snapshot WHERE screening_id=4", Integer.class));
        jdbc.update("DELETE FROM screening_capacity_snapshot WHERE screening_id=1");
        ScreeningCapacity.capture(jdbc, 1, 1);
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM screening_capacity_snapshot WHERE screening_id=1", Integer.class));
        var halls = new HallSeatService(jdbc, mock(StringRedisTemplate.class));
        var error = assertThrows(BusinessException.class, () -> halls.batch(1,
                new HallSeatService.BatchInput(List.of(1L), "DISABLED")));
        assertEquals(409, error.getCode());
        assertEquals(2, jdbc.queryForObject("SELECT sellable_seat_count FROM screening_capacity_snapshot WHERE screening_id=4", Integer.class));
    }

    @Test
    void csvExportsSeparateMoneyEventsPreserveTicketsAndNeutralizeFormulas() {
        jdbc.update("UPDATE movie SET title='  =HYPERLINK(\"bad\")' WHERE id=1");
        String csv = new String(exports.sales(filter(DAY.minusDays(1), DAY.plusDays(1))), StandardCharsets.UTF_8);
        assertTrue(csv.startsWith("\ufeff"));
        assertEquals(4, csv.lines().count());
        assertTrue(csv.contains("'  =HYPERLINK("));
        assertTrue(csv.contains("\"退款处理日\""));
        assertTrue(csv.contains("\"0.00\",\"80.00\",\"0\",\"2\""));
        assertTrue(new String(exports.occupancy(filter(DAY, DAY)), StandardCharsets.UTF_8).contains("历史容量未知"));
    }

    @Test
    void schemaUpgradeCanBeRepeatedWithoutReplayingOrDeletingBusinessData() throws Exception {
        jdbc.execute("DROP TABLE screening_capacity_snapshot");
        jdbc.execute("ALTER TABLE refund_record DROP COLUMN refunded_at");
        var initializer = new SalesReportSchemaInitializer(jdbc.getDataSource());
        initializer.run(null);
        initializer.run(null);
        assertEquals(4, jdbc.queryForObject("SELECT COUNT(*) FROM ticket_order", Integer.class));
        assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM refund_record", Integer.class));
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM screening_capacity_snapshot", Integer.class));
        jdbc.update("UPDATE refund_record SET refunded_at='2026-10-11 00:00:00' WHERE id=1");
        assertEquals(new BigDecimal("80.00"), sales.sales(filter(DAY.plusDays(1), DAY.plusDays(1))).summary().refundAmount());
    }

    @Test
    void csvPaginationRetainsTheFinalPageWithoutDuplicatingMoney() {
        for (int id = 10; id < 511; id++) {
            jdbc.update("INSERT INTO payment_transaction VALUES(?,1,1.25,'SUCCESS','2026-10-10 08:00:00',?)", id, "PAGE-" + id);
        }
        String csv = new String(exports.sales(filter(DAY, DAY)), StandardCharsets.UTF_8);
        assertEquals(503, csv.lines().count()); // Header, existing payment, and all 501 added events.
        assertEquals(1, csv.lines().filter(line -> line.contains("\"PAGE-510\"")).count());
        assertEquals(new BigDecimal("706.25"), sales.sales(filter(DAY, DAY)).summary().paidAmount());
    }

    @Test
    void adminContractsValidateDatesEmitSimulationAndRejectOrdinaryUsers() throws Exception {
        mvc.perform(get("/api/admin/reports/sales").header("X-Auth-Token", "admin").param("from", DAY.toString()).param("to", DAY.toString()))
                .andExpect(status().isOk()).andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.data.metadata.dataMode").value("SIMULATED"))
                .andExpect(jsonPath("$.data.metadata.timeZone").value("Asia/Shanghai"))
                .andExpect(jsonPath("$.data.summary.paidAmount").value("80.00"));
        for (String path : List.of("sales", "occupancy", "sales/export", "occupancy/export")) {
            mvc.perform(get("/api/admin/reports/" + path).header("X-Auth-Token", "user").param("from", DAY.toString()).param("to", DAY.toString()))
                    .andExpect(status().isForbidden());
            mvc.perform(get("/api/admin/reports/" + path).param("from", DAY.toString()).param("to", DAY.toString()))
                    .andExpect(status().isUnauthorized());
        }
        mvc.perform(get("/api/admin/reports/sales").header("X-Auth-Token", "admin").param("from", "2026-10-01").param("to", "2026-11-01"))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/api/admin/reports/sales").header("X-Auth-Token", "admin").param("from", "invalid").param("to", DAY.toString()))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/api/admin/reports/sales/export").header("X-Auth-Token", "admin").param("from", DAY.toString()).param("to", DAY.toString()))
                .andExpect(status().isOk()).andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(content().contentType("text/csv;charset=UTF-8"));
    }
}
