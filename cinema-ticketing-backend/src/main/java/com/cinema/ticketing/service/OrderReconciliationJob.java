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
 * <p>所以这里不依赖任何中间件，直接按 {@code expire_at} 扫库取消。正常情况下扫不到东西
 * （消息总会先一步到达），扫到就说明上游丢消息了，用 WARN 记一笔。
 *
 * <p>已知边界：没有做多实例互斥。多副本部署时几个实例会同时扫到同一批订单，靠
 * {@code UPDATE ... WHERE status = 'UNPAID'} 的行锁保证只有一方真正取消，结果正确但日志会重复。
 * 真要多副本，应该把这条查询换成 {@code FOR UPDATE SKIP LOCKED}。
 */
@Component
public class OrderReconciliationJob {

    private static final Logger log = LoggerFactory.getLogger(OrderReconciliationJob.class);

    /** 单次最多处理的订单数，避免积压时一次扫太久。 */
    private static final int BATCH_SIZE = 200;

    private final JdbcTemplate jdbcTemplate;
    private final OrderService orderService;

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
                if (orderService.cancelOverdueOrder(orderNo)) {
                    cancelled++;
                } else {
                    skipped++;
                }
            } catch (Exception exception) {
                // 单笔失败不影响其余订单；下一轮还会再扫到它。
                log.error("对账取消失败: {}", orderNo, exception);
            }
        }
        // 扫到东西本身就是异常信号：说明延迟消息没送到。
        log.warn("对账兜底：扫描到 {} 笔已过期仍未支付的订单，实际取消 {} 笔，跳过 {} 笔（跳过=已被其他路径处理）",
                orderNos.size(), cancelled, skipped);
    }
}
