package com.cinema.ticketing.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;

/** Upgrades existing review tables without replaying seed data or granting viewing qualification. */
@Component
@ConditionalOnProperty(name = "reviews.initialize-schema", havingValue = "true", matchIfMissing = true)
public class MovieReviewSchemaInitializer implements ApplicationRunner {
    private final DataSource dataSource;

    public MovieReviewSchemaInitializer(DataSource dataSource) { this.dataSource = dataSource; }

    @Override
    public void run(ApplicationArguments args) throws SQLException {
        try (Connection connection = dataSource.getConnection(); var statement = connection.createStatement()) {
            try (var lock = statement.executeQuery("SELECT GET_LOCK('cinema_movie_review_schema_v2', 60)")) {
                if (!lock.next() || lock.getInt(1) != 1) throw new SQLException("无法取得影评结构升级锁");
            }
            try {
                new ResourceDatabasePopulator(new ClassPathResource("movie-review-schema.sql")).populate(connection);
                Map<String, String> columns = new LinkedHashMap<>();
                columns.put("status", "VARCHAR(32) NOT NULL DEFAULT 'PENDING'");
                columns.put("revision", "BIGINT NOT NULL DEFAULT 1");
                columns.put("moderation_note", "VARCHAR(1000) NOT NULL DEFAULT ''");
                columns.put("moderated_by", "BIGINT NULL");
                columns.put("moderated_at", "DATETIME NULL");
                for (var column : columns.entrySet()) addColumn(connection, "movie_review", column.getKey(), column.getValue());
                addColumn(connection, "order_item", "checked_in_at", "DATETIME NULL");
                addColumn(connection, "order_item", "checked_in_by", "BIGINT NULL");
            } finally {
                statement.execute("SELECT RELEASE_LOCK('cinema_movie_review_schema_v2')");
            }
        }
    }

    private void addColumn(Connection connection, String table, String name, String definition) throws SQLException {
        try (var columns = connection.getMetaData().getColumns(connection.getCatalog(), null, table, name)) {
            if (columns.next()) return;
        }
        try (var statement = connection.createStatement()) {
            statement.execute("ALTER TABLE " + table + " ADD COLUMN " + name + " " + definition);
        }
    }
}
