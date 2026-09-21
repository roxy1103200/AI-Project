package com.cinema.ticketing.mq;

import com.cinema.ticketing.config.RabbitMqConfiguration;
import com.cinema.ticketing.service.OrderService;
import com.rabbitmq.client.Channel;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

import java.io.IOException;

@Component
public class OrderCancelConsumer {

    private static final Logger log = LoggerFactory.getLogger(OrderCancelConsumer.class);
    private static final int MAX_ATTEMPTS = 3;

    private final OrderService orderService;
    private final RabbitTemplate rabbitTemplate;

    public OrderCancelConsumer(OrderService orderService, RabbitTemplate rabbitTemplate) {
        this.orderService = orderService;
        this.rabbitTemplate = rabbitTemplate;
    }

    @RabbitListener(queues = RabbitMqConfiguration.CANCEL_QUEUE)
    public void consume(OrderCancelMessage event, Message message, Channel channel) throws IOException {
        long deliveryTag = message.getMessageProperties().getDeliveryTag();
        try {
            orderService.cancelIfUnpaid(event.messageId(), event.orderNo());
            channel.basicAck(deliveryTag, false);
        } catch (Exception exception) {
            if (event.attempt() < MAX_ATTEMPTS - 1) {
                log.warn("订单取消处理失败，将进行第 {} 次重试: {}", event.attempt() + 1, event.orderNo(), exception);
                rabbitTemplate.convertAndSend("", RabbitMqConfiguration.CANCEL_RETRY_QUEUE, event.nextAttempt());
                channel.basicAck(deliveryTag, false);
                return;
            }
            log.error("订单取消处理失败，进入死信队列: {}", event.orderNo(), exception);
            channel.basicReject(deliveryTag, false);
        }
    }
}
