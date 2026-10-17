package com.cinema.ticketing.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 超时订单的对账兜底。
 *
 * <p>正常路径是订单创建时投一条延迟消息，到期由 {@code OrderCancelConsumer} 消费取消。但消息
 * 中间件不保证一定送达：重试耗尽后消息进 {@code order.cancel.failed}，而那个队列**没有消费者**；
 * 发布与 ack 之间宕机也会丢消息。一旦丢了，订单就永远停在 {@code UNPAID}、座位锁也不释放，
 * 而且没有任何人会知道。
 *
 * <p>按 {@code expire_at} 扫描；支付宝订单先核对/关闭渠道交易再取消，渠道未确认时保留占位。
 * 模拟订单沿用本地幂等取消。支付宝查询通过支付单租约协调多实例。
 */
@Component
public class OrderReconciliationJob {

    private static final Logger log = LoggerFactory.getLogger(OrderReconciliationJob.class);

    /** 单次最多处理的订单数，避免积压时一次扫太久。 */
    private static final int BATCH_SIZE = 200;

    private final JdbcTemplate jdbcTemplate;
    private final OrderService orderService;
    private com.cinema.ticketing.payment.PaymentService payments;

    @org.springframework.beans.factory.annotation.Autowired
    public void configurePayments(com.cinema.ticketing.payment.PaymentService payments) { this.payments = payments; }

    public OrderReconciliationJob(JdbcTemplate jdbcTemplate, OrderService orderService) {
        this.jdbcTemplate = jdbcTemplate;
        this.orderService = orderService;
    }

    @Scheduled(fixedDelayString = "${order.reconcile.fixed-delay-ms:60000}",
            initialDelayString = "${order.reconcile.initial-delay-ms:60000}")
    public void cancelOverdueOrders() {
        List<String> orderNos = jdbcTemplate.queryForList(
                "SELECT order_no FROM ticket_order WHERE status = 'UNPAID' AND expire_at <= ? ORDER BY id LIMIT ?",
                String.class, LocalDateTime.now(), BATCH_SIZE);
        if (orderNos.isEmpty()) {
            return;
        }
        int cancelled = 0;
        int skipped = 0;
        for (String orderNo : orderNos) {
            try {
                if (payments != null && payments.manages(orderNo) ? payments.cancelOverdue(orderNo)
                        : orderService.cancelOverdueOrder(orderNo)) {
                    cancelled++;
                } else {
                    skipped++;
                }
            } catch (Exception exception) {
                // 单笔失败不影响其余订单；下一轮还会再扫到它。
                log.error("对账取消失败: {}", orderNo, exception);
            }
        }
        log.info("到期订单对账：扫描 {} 笔，已取消 {} 笔，待渠道确认或已处理 {} 笔",
                orderNos.size(), cancelled, skipped);
    }
}
