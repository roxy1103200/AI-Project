package com.cinema.ticketing.mq;

import com.cinema.ticketing.config.RabbitMqConfiguration;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Duration;

@Component
public class OrderMessagePublisher {

    private static final long MIN_EXPIRATION_MILLIS = 1000L;

    private final RabbitTemplate rabbitTemplate;

    public OrderMessagePublisher(RabbitTemplate rabbitTemplate) {
        this.rabbitTemplate = rabbitTemplate;
    }

    /**
     * 投递一条延迟取消消息。
     *
     * <p>参数是「还有多久到期」这个时长本身，不是到期时刻 —— 调用方算 expireAt 时已经读过一次
     * 时钟，这里若再读一次来求差，得到的 TTL 会比真实剩余时间短几毫秒，消息就会在 expire_at
     * 之前几毫秒落地，被 cancelIfUnpaid 的到期判断打回，白白烧掉一次重试。
     */
    public void scheduleCancellation(String orderNo, Duration delay) {
        OrderCancelMessage message = new OrderCancelMessage("order-cancel:" + orderNo, orderNo, 0);
        String expiration = expirationFrom(delay);
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

    /**
     * RabbitMQ 的 per-message TTL 必须是正数，0 会被当成「立即过期」。这里兜一个下限，
     * 免得调用方传进 0 或负数时消息在队列里瞬间过期、把订单直接取消掉。
     */
    private String expirationFrom(Duration delay) {
        return String.valueOf(Math.max(MIN_EXPIRATION_MILLIS, delay.toMillis()));
    }
}
