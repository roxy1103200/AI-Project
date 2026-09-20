package com.cinema.ticketing.config;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Configuration;

@Configuration
@MapperScan("com.cinema.ticketing.mapper")
public class MyBatisConfiguration {
}
