package com.cinema.ticketing.payment;

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
import java.util.LinkedHashMap;
import java.util.Map;

@Component
@Order(-80)
@ConditionalOnProperty(name = "payment.initialize-schema", havingValue = "true", matchIfMissing = true)
public class PaymentSchemaInitializer implements ApplicationRunner {
    private final DataSource source;
    public PaymentSchemaInitializer(DataSource source) { this.source = source; }

    @Override
    public void run(ApplicationArguments arguments) throws SQLException {
        try (Connection connection = source.getConnection(); var statement = connection.createStatement()) {
            boolean mysql = "MySQL".equals(connection.getMetaData().getDatabaseProductName());
            if (mysql) {
                try (var result = statement.executeQuery("SELECT GET_LOCK('cinema_payment_schema_v1',60)")) {
                    if (!result.next() || result.getInt(1) != 1) throw new SQLException("无法取得支付升级锁");
                }
            }
            try {
                new ResourceDatabasePopulator(new ClassPathResource("payment-schema.sql")).populate(connection);
                columns(connection, "payment_transaction", Map.of("channel", "VARCHAR(16) NOT NULL DEFAULT 'MOCK'",
                        "environment", "VARCHAR(16) NOT NULL DEFAULT 'MOCK'", "channel_trade_no", "VARCHAR(64)", "payment_order_id", "BIGINT"));
                unique(connection, "payment_transaction", "uk_receipt_channel_payment", "payment_order_id");
                var refund = new LinkedHashMap<String, String>();
                refund.put("refund_no", "VARCHAR(64)");
                refund.put("payment_order_id", "BIGINT");
                refund.put("channel", "VARCHAR(16) NOT NULL DEFAULT 'MOCK'");
                refund.put("environment", "VARCHAR(16) NOT NULL DEFAULT 'MOCK'");
                refund.put("reason_type", "VARCHAR(32)");
                refund.put("policy_version", "VARCHAR(64)");
                refund.put("requested_at", "DATETIME");
                refund.put("attempts", "INT NOT NULL DEFAULT 0");
                refund.put("next_check_at", "DATETIME");
                refund.put("lease_owner", "VARCHAR(64)");
                refund.put("lease_until", "DATETIME");
                refund.put("last_error_code", "VARCHAR(64)");
                columns(connection, "refund_record", refund);
                unique(connection, "refund_record", "uk_channel_refund_no", "refund_no");
                unique(connection, "refund_record", "uk_channel_refund_payment", "payment_order_id");
                index(connection, "refund_record", "idx_channel_refund_check", "status,next_check_at,lease_until");
                statement.executeUpdate("UPDATE refund_record SET channel='MOCK',environment='MOCK' WHERE payment_order_id IS NULL");
            } finally {
                if (mysql) statement.execute("SELECT RELEASE_LOCK('cinema_payment_schema_v1')");
            }
        }
    }

    private void columns(Connection connection, String table, Map<String, String> columns) throws SQLException {
        for (var column : columns.entrySet()) {
            boolean exists = false;
            try (var result = connection.getMetaData().getColumns(connection.getCatalog(), null, table, null)) {
                while (result.next()) if (column.getKey().equalsIgnoreCase(result.getString("COLUMN_NAME"))) exists = true;
            }
            if (!exists) try (var statement = connection.createStatement()) {
                statement.execute("ALTER TABLE " + table + " ADD COLUMN " + column.getKey() + " " + column.getValue());
            }
        }
    }

    private void unique(Connection connection, String table, String name, String column) throws SQLException {
        index(connection, table, name, column, true);
    }

    private void index(Connection connection, String table, String name, String columns) throws SQLException {
        index(connection, table, name, columns, false);
    }

    private void index(Connection connection, String table, String name, String columns, boolean unique) throws SQLException {
        try (var indices = connection.getMetaData().getIndexInfo(connection.getCatalog(), null, table, false, false)) {
            while (indices.next()) if (name.equalsIgnoreCase(indices.getString("INDEX_NAME"))) return;
        }
        try (var statement = connection.createStatement()) {
            statement.execute("CREATE " + (unique ? "UNIQUE " : "") + "INDEX " + name + " ON " + table + "(" + columns + ")");
        }
    }
}
