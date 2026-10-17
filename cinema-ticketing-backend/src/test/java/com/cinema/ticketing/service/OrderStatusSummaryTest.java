package com.cinema.ticketing.service;

import static org.junit.jupiter.api.Assertions.*;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class OrderStatusSummaryTest {
    private static final LocalDateTime NOW = LocalDateTime.of(2026, 10, 17, 12, 0);

    private Map<String, Object> order(String status) {
        Map<String, Object> order = new HashMap<>();
        order.put("status", status); order.put("start_time", NOW.plusHours(3));
        order.put("refund_cutoff_minutes", 30); order.put("has_check_in", false);
        return order;
    }

    @Test void pendingAndUnknownRefundsCannotBeUsedOrRequestedAgain() {
        for (String refund : new String[]{"PENDING", "UNKNOWN"}) {
            var order = order("REFUNDING"); order.put("payment_status", "SUCCESS"); order.put("refund_status", refund);
            OrderStatusSummary.decorate(order, NOW);
            assertEquals(false, order.get("can_refund"));
            assertTrue(order.get("refund_reason").toString().contains("电影票暂不可使用"));
            assertEquals("cinema-order-v2", order.get("contract_version"));
        }
    }

    @Test void closingDoesNotClaimTheOrderWasCancelled() {
        var order = order("UNPAID"); order.put("payment_status", "CLOSING");
        OrderStatusSummary.decorate(order, NOW);
        assertTrue(order.get("refund_reason").toString().contains("尚未确认取消"));
    }

    @Test void compensationRefundPreservesCancelledOrderAndPaymentFacts() {
        var order = order("CANCELLED"); order.put("payment_status", "SUCCESS");
        order.put("refund_reason_type", "LATE_PAYMENT"); order.put("refund_status", "UNKNOWN");
        OrderStatusSummary.decorate(order, NOW);
        assertTrue(order.get("refund_reason").toString().contains("已收款项"));
        order.put("refund_status", "REFUNDED"); OrderStatusSummary.decorate(order, NOW);
        assertTrue(order.get("refund_reason").toString().contains("补偿退款已确认"));
        assertEquals("CANCELLED", order.get("status"));
    }

    @Test void checkedInReasonTakesPriorityOverTheCutoff() {
        var order = order("ISSUED"); order.put("has_check_in", true); order.put("start_time", NOW.minusHours(1));
        OrderStatusSummary.decorate(order, NOW);
        assertTrue(order.get("refund_reason").toString().contains("验票"));
        assertEquals(false, order.get("can_refund"));
    }

    @Test void issuedAndUnpaidOrdersHaveDifferentEligibility() {
        var issued = order("ISSUED"); OrderStatusSummary.decorate(issued, NOW); assertEquals(true, issued.get("can_refund"));
        var unpaid = order("UNPAID"); OrderStatusSummary.decorate(unpaid, NOW); assertEquals(false, unpaid.get("can_refund"));
        assertEquals("NOT_STARTED", unpaid.get("payment_status"));
    }
}
