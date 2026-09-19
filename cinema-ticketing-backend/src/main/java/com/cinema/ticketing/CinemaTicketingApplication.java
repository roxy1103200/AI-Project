package com.cinema.ticketing;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MapperScan("com.cinema.ticketing")
public class CinemaTicketingApplication {

    public static void main(String[] args) {
        SpringApplication.run(CinemaTicketingApplication.class, args);
    }
}
