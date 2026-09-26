package com.cinema.ticketing.service;

import com.cinema.ticketing.mq.OrderMessagePublisher;
import com.cinema.ticketing.common.BusinessException;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.dao.DataAccessResourceFailureException;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

class OrderServiceValidationTest {

    private final OrderService orderService = new OrderService(
            mock(JdbcTemplate.class), mock(StringRedisTemplate.class), mock(OrderMessagePublisher.class));

    @Test
    void rejectsEmptySeatSelectionBeforeDatabaseAccess() {
        assertThrows(BusinessException.class, () -> orderService.lockSeats("owner", 1L, List.of()));
    }

    @Test
    void rejectsDuplicateSeatSelection() {
        assertThrows(BusinessException.class, () -> orderService.lockSeats("owner", 1L, List.of(10L, 10L)));
    }

    @Test
    void databaseOutageIsNotReportedAsMissingScreeningOrOrder() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        OrderService service = new OrderService(jdbc, mock(StringRedisTemplate.class), mock(OrderMessagePublisher.class));
        when(jdbc.queryForObject(anyString(), any(RowMapper.class), eq(1L)))
                .thenThrow(new DataAccessResourceFailureException("database unavailable"));
        assertThrows(DataAccessResourceFailureException.class,
                () -> service.lockSeats("owner", 1L, List.of(10L)));
        when(jdbc.queryForObject(anyString(), any(RowMapper.class), eq("order-1"), eq(1L)))
                .thenThrow(new DataAccessResourceFailureException("database unavailable"));
        assertThrows(DataAccessResourceFailureException.class,
                () -> service.findOrder(1L, "order-1"));
    }
}
