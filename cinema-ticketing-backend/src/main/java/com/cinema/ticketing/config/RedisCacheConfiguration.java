package com.cinema.ticketing.config;

import org.springframework.boot.autoconfigure.cache.RedisCacheManagerBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import java.time.Duration;

@Configuration
public class RedisCacheConfiguration {

    @Bean
    public RedisCacheManagerBuilderCustomizer redisCacheDefaults() {
        return builder -> builder.withCacheConfiguration("catalogList", cacheConfiguration())
                .withCacheConfiguration("catalogDetail", cacheConfiguration());
    }

    private org.springframework.data.redis.cache.RedisCacheConfiguration cacheConfiguration() {
        return org.springframework.data.redis.cache.RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(Duration.ofMinutes(5))
                .disableCachingNullValues();
    }
}
