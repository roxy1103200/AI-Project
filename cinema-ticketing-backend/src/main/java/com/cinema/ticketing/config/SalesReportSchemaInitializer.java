package com.cinema.ticketing.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.stereotype.Component;
import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;

/** Add report facts without replaying seeds or inventing historical screening capacity. */
@Component
@Order(-90)
@ConditionalOnProperty(name = "reports.initialize-schema", havingValue = "true", matchIfMissing = true)
public class SalesReportSchemaInitializer implements ApplicationRunner {
    public static final String NORMALIZE_REFUND_TIME_SQL = "UPDATE refund_record SET refunded_at=TIMESTAMPADD(SECOND,UNIX_TIMESTAMP(created_at),"
            + "'1970-01-01 08:00:00') WHERE refunded_at IS NULL";
    private final DataSource source;
    public SalesReportSchemaInitializer(DataSource source) { this.source = source; }

    @Override
    public void run(ApplicationArguments args) throws SQLException {
        try (Connection connection = source.getConnection(); var statement = connection.createStatement()) {
            boolean mysql = "MySQL".equals(connection.getMetaData().getDatabaseProductName());
            if (mysql) {
                try (var result = statement.executeQuery("SELECT GET_LOCK('cinema_sales_report_schema_v1', 60)")) {
                    if (!result.next() || result.getInt(1) != 1) throw new SQLException("无法取得经营报表升级锁");
                }
            }
            try {
                new ResourceDatabasePopulator(new ClassPathResource("sales-report-schema.sql")).populate(connection);
                try (var columns = connection.getMetaData().getColumns(connection.getCatalog(), null, "refund_record", "refunded_at")) {
                    if (!columns.next()) statement.execute("ALTER TABLE refund_record ADD COLUMN refunded_at DATETIME NULL");
                }
                if (mysql) {
                    // UNIX_TIMESTAMP reads the TIMESTAMP instant; adding to a literal avoids session timezone dependence.
                    statement.executeUpdate(NORMALIZE_REFUND_TIME_SQL);
                }
                index(connection, "payment_transaction", "idx_payment_report_time", "status,paid_at,order_id");
                index(connection, "refund_record", "idx_refund_report_time", "status,refunded_at,order_id");
            } finally {
                if (mysql) statement.execute("SELECT RELEASE_LOCK('cinema_sales_report_schema_v1')");
            }
        }
    }

    private void index(Connection connection, String table, String name, String columns) throws SQLException {
        try (var indices = connection.getMetaData().getIndexInfo(connection.getCatalog(), null, table, false, false)) {
            while (indices.next()) if (name.equalsIgnoreCase(indices.getString("INDEX_NAME"))) return;
        }
        try (var statement = connection.createStatement()) {
            statement.execute("CREATE INDEX " + name + " ON " + table + "(" + columns + ")");
        }
    }
}
