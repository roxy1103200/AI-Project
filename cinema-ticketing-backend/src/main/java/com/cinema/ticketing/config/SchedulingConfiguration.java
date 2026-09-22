package com.cinema.ticketing.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 开启定时任务。目前只有 {@code OrderReconciliationJob} 一个使用方。
 *
 * <p>单独放一个配置类，而不是把 {@code @EnableScheduling} 挂到启动类上，
 * 是为了让「谁在用定时任务」这件事在 config 包里一眼可见。
 */
@Configuration
@EnableScheduling
public class SchedulingConfiguration {
}
