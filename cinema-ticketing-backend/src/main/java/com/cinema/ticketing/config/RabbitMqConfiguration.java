package com.cinema.ticketing.config;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.rabbit.config.SimpleRabbitListenerContainerFactory;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.boot.autoconfigure.amqp.SimpleRabbitListenerContainerFactoryConfigurer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Qualifier;

import java.util.Map;

@Configuration
public class RabbitMqConfiguration {

    public static final String ORDER_EXCHANGE = "cinema.order.exchange";
    public static final String ORDER_DEAD_EXCHANGE = "cinema.order.dead.exchange";
    public static final String CANCEL_DELAY_QUEUE = "order.cancel.delay";
    public static final String CANCEL_RETRY_QUEUE = "order.cancel.retry";
    public static final String CANCEL_QUEUE = "order.cancel";
    public static final String CANCEL_FAILED_QUEUE = "order.cancel.failed";
    public static final String CANCEL_DELAY_KEY = "order.cancel.delay";
    public static final String CANCEL_KEY = "order.cancel";
    public static final String CANCEL_FAILED_KEY = "order.cancel.failed";

    @Bean
    public DirectExchange orderExchange() {
        return new DirectExchange(ORDER_EXCHANGE);
    }

    @Bean
    public DirectExchange orderDeadExchange() {
        return new DirectExchange(ORDER_DEAD_EXCHANGE);
    }

    @Bean
    public Queue cancelDelayQueue() {
        return new Queue(CANCEL_DELAY_QUEUE, true, false, false, Map.of(
                "x-dead-letter-exchange", ORDER_EXCHANGE,
                "x-dead-letter-routing-key", CANCEL_KEY));
    }

    @Bean
    public Queue cancelRetryQueue() {
        return new Queue(CANCEL_RETRY_QUEUE, true, false, false, Map.of(
                "x-message-ttl", 5000,
                "x-dead-letter-exchange", ORDER_EXCHANGE,
                "x-dead-letter-routing-key", CANCEL_KEY));
    }

    @Bean
    public Queue cancelQueue() {
        return new Queue(CANCEL_QUEUE, true, false, false, Map.of(
                "x-dead-letter-exchange", ORDER_DEAD_EXCHANGE,
                "x-dead-letter-routing-key", CANCEL_FAILED_KEY));
    }

    @Bean
    public Queue cancelFailedQueue() {
        return new Queue(CANCEL_FAILED_QUEUE, true);
    }

    @Bean
    public Binding cancelDelayBinding(@Qualifier("cancelDelayQueue") Queue cancelDelayQueue,
                                     @Qualifier("orderExchange") DirectExchange orderExchange) {
        return BindingBuilder.bind(cancelDelayQueue).to(orderExchange).with(CANCEL_DELAY_KEY);
    }

    @Bean
    public Binding cancelBinding(@Qualifier("cancelQueue") Queue cancelQueue,
                                 @Qualifier("orderExchange") DirectExchange orderExchange) {
        return BindingBuilder.bind(cancelQueue).to(orderExchange).with(CANCEL_KEY);
    }

    @Bean
    public Binding cancelFailedBinding(@Qualifier("cancelFailedQueue") Queue cancelFailedQueue,
                                       @Qualifier("orderDeadExchange") DirectExchange orderDeadExchange) {
        return BindingBuilder.bind(cancelFailedQueue).to(orderDeadExchange).with(CANCEL_FAILED_KEY);
    }

    @Bean
    public MessageConverter rabbitMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }

    @Bean
    public SimpleRabbitListenerContainerFactory rabbitListenerContainerFactory(
            ConnectionFactory connectionFactory,
            SimpleRabbitListenerContainerFactoryConfigurer configurer,
            MessageConverter rabbitMessageConverter) {
        SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
        configurer.configure(factory, connectionFactory);
        factory.setMessageConverter(rabbitMessageConverter);
        factory.setAcknowledgeMode(org.springframework.amqp.core.AcknowledgeMode.MANUAL);
        factory.setDefaultRequeueRejected(false);
        factory.setPrefetchCount(10);
        return factory;
    }
}
