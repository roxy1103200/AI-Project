package com.cinema.ticketing.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;

/** Adds only the feedback table; never replays cinema seed data. */
@Component
@ConditionalOnProperty(name = "ai.feedback.initialize-schema", havingValue = "true", matchIfMissing = true)
public class AiFeedbackSchemaInitializer implements ApplicationRunner {
    private final DataSource dataSource;

    public AiFeedbackSchemaInitializer(DataSource dataSource) { this.dataSource = dataSource; }

    @Override
    public void run(ApplicationArguments args) {
        new ResourceDatabasePopulator(new ClassPathResource("ai-feedback-schema.sql")).execute(dataSource);
    }
}
