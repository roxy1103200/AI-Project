package com.cinema.ticketing.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** Add only the durable revocation version; never replay user seed data. */
@Component
@Order(-100)
@ConditionalOnProperty(name = "auth.initialize-schema", havingValue = "true", matchIfMissing = true)
public class AccountSecuritySchemaInitializer implements ApplicationRunner {
    private final JdbcTemplate jdbc;

    public AccountSecuritySchemaInitializer(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (exists()) return;
        try {
            jdbc.execute("ALTER TABLE users ADD COLUMN session_version BIGINT NOT NULL DEFAULT 0");
        } catch (DataAccessException exception) {
            // Another application instance may have completed the same migration.
            if (!exists()) throw exception;
        }
    }

    private boolean exists() {
        return Boolean.TRUE.equals(
                jdbc.execute(
                        (org.springframework.jdbc.core.ConnectionCallback<Boolean>)
                                connection -> {
                                    try (var columns =
                                            connection
                                                    .getMetaData()
                                                    .getColumns(
                                                            connection.getCatalog(),
                                                            null,
                                                            "users",
                                                            "session_version")) {
                                        return columns.next();
                                    }
                                }));
    }
}
