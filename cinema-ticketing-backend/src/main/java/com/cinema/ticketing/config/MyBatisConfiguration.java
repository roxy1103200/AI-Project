package com.cinema.ticketing.config;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.context.annotation.Configuration;
import org.apache.ibatis.session.SqlSessionFactory;

@Configuration
@ConditionalOnBean(SqlSessionFactory.class)
@MapperScan("com.cinema.ticketing")
public class MyBatisConfiguration {
}
