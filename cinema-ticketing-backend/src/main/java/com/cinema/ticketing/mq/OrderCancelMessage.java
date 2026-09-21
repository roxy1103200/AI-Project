package com.cinema.ticketing.mq;

public record OrderCancelMessage(String messageId, String orderNo, int attempt) {

    public OrderCancelMessage nextAttempt() {
        return new OrderCancelMessage(messageId, orderNo, attempt + 1);
    }
}
