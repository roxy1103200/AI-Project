package com.cinema.ticketing.service;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.LocalDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OrderReconciliationJobTest {

    private final JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
    private final OrderService orderService = mock(OrderService.class);
    private final OrderReconciliationJob job = new OrderReconciliationJob(jdbcTemplate, orderService);

    /** 一笔失败不能带走后面的订单 —— 否则排在前面的坏数据会让整批兜底失效。 */
    @Test
    void cancelsEveryOverdueOrderEvenWhenOneFails() {
        stubOverdueOrders(List.of("OA", "OB", "OC"));
        when(orderService.cancelOverdueOrder("OA")).thenThrow(new IllegalStateException("boom"));
        when(orderService.cancelOverdueOrder("OB")).thenReturn(true);
        when(orderService.cancelOverdueOrder("OC")).thenReturn(false);

        job.cancelOverdueOrders();

        verify(orderService).cancelOverdueOrder("OA");
        verify(orderService).cancelOverdueOrder("OB");
        verify(orderService).cancelOverdueOrder("OC");
    }

    @Test
    void doesNothingWhenNothingIsOverdue() {
        stubOverdueOrders(List.of());

        job.cancelOverdueOrders();

        verify(orderService, never()).cancelOverdueOrder(anyString());
    }

    private void stubOverdueOrders(List<String> orderNos) {
        when(jdbcTemplate.queryForList(startsWith("SELECT order_no"), eq(String.class),
                any(LocalDateTime.class), any(Integer.class))).thenReturn(orderNos);
    }
}
