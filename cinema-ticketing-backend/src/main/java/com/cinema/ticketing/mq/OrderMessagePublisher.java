package com.cinema.ticketing.mq;

import com.cinema.ticketing.config.RabbitMqConfiguration;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Duration;
import java.time.LocalDateTime;

@Component
public class OrderMessagePublisher {

    private final RabbitTemplate rabbitTemplate;

    public OrderMessagePublisher(RabbitTemplate rabbitTemplate) {
        this.rabbitTemplate = rabbitTemplate;
    }

    public void scheduleCancellation(String orderNo, LocalDateTime expireAt) {
        OrderCancelMessage message = new OrderCancelMessage("order-cancel:" + orderNo, orderNo, 0);
        String expiration = expirationFrom(expireAt);
        Runnable publish = () -> rabbitTemplate.convertAndSend(
                RabbitMqConfiguration.ORDER_EXCHANGE,
                RabbitMqConfiguration.CANCEL_DELAY_KEY,
                message,
                outgoingMessage -> {
                    outgoingMessage.getMessageProperties().setExpiration(expiration);
                    return outgoingMessage;
                });
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    publish.run();
                }
            });
        } else {
            publish.run();
        }
    }

    private String expirationFrom(LocalDateTime expireAt) {
        long millis = Math.max(1000, Duration.between(LocalDateTime.now(), expireAt).toMillis());
        return String.valueOf(millis);
    }
}
