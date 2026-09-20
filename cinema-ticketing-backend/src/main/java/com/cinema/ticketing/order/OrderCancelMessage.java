package com.cinema.ticketing.order;

public record OrderCancelMessage(String messageId, String orderNo, int attempt) {

    public OrderCancelMessage nextAttempt() {
        return new OrderCancelMessage(messageId, orderNo, attempt + 1);
    }
}
