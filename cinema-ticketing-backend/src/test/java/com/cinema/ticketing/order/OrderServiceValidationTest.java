package com.cinema.ticketing.order;

import com.cinema.ticketing.common.BusinessException;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;

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
}
