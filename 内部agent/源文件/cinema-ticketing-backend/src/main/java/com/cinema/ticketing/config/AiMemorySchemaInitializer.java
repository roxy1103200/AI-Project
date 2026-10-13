package com.cinema.ticketing.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;

/** 只创建记忆与索引任务表，不重放影片和用户种子数据。 */
@Component
@ConditionalOnProperty(
        name = "ai.memory.initialize-schema",
        havingValue = "true",
        matchIfMissing = true)
public class AiMemorySchemaInitializer implements ApplicationRunner {
    private final DataSource dataSource;

    public AiMemorySchemaInitializer(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public void run(ApplicationArguments args) {
        new ResourceDatabasePopulator(new ClassPathResource("ai-memory-schema.sql"))
                .execute(dataSource);
    }
}
