package com.cinema.ticketing.payment;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import java.util.List;

/** Best effort after commit; SQL order states remain the seat occupancy authority. */
@Component
public class PaymentSeatRelease {
    private static final Logger log = LoggerFactory.getLogger(PaymentSeatRelease.class);
    private static final DefaultRedisScript<Long> UNLOCK = new DefaultRedisScript<>(
            "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end return 0", Long.class);
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    public PaymentSeatRelease(JdbcTemplate jdbc, StringRedisTemplate redis) { this.jdbc = jdbc; this.redis = redis; }

    public void release(PaymentStore.Payment payment) {
        if ("UNPAID".equals(payment.orderStatus()) || "REFUNDING".equals(payment.orderStatus())) return;
        try {
            var order = jdbc.queryForMap("SELECT screening_id,lock_owner FROM ticket_order WHERE id=?", payment.orderId());
            for (Long seat : jdbc.queryForList("SELECT seat_id FROM order_item WHERE order_id=?", Long.class, payment.orderId())) {
                redis.execute(UNLOCK, List.of("seat:lock:" + order.get("screening_id") + ":" + seat), order.get("lock_owner"));
            }
        } catch (RuntimeException exception) {
            log.warn("支付后座位缓存释放失败，等待缓存过期，支付单 {}", payment.paymentNo());
        }
    }
}
