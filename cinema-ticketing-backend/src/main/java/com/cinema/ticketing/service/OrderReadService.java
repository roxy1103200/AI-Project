package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.JdbcTimes;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;

/** User-scoped read model shared by the website and Java's private AI endpoint. */
public class OrderReadService {
    private static final String SELECT = "SELECT o.id,o.order_no,o.user_id,o.screening_id,o.total_amount,o.status,"
            + "o.expire_at,o.paid_at,o.created_at,m.title movie_title,s.start_time,h.name hall_name,c.name cinema_name,"
            + "p.cutoff_minutes refund_cutoff_minutes,COALESCE(cp.status,CASE WHEN pt.status='SUCCESS' THEN 'SUCCESS' ELSE 'NOT_STARTED' END) payment_status,cr.status refund_status,"
            + "cr.reason_type refund_reason_type,EXISTS(SELECT 1 FROM order_item i WHERE i.order_id=o.id "
            + "AND i.checked_in_at IS NOT NULL) has_check_in FROM ticket_order o JOIN screening s ON s.id=o.screening_id "
            + "JOIN movie m ON m.id=s.movie_id JOIN hall h ON h.id=s.hall_id JOIN cinema c ON c.id=h.cinema_id "
            + "LEFT JOIN refund_policy p ON p.id=(SELECT MAX(id) FROM refund_policy WHERE enabled=TRUE) "
            + "LEFT JOIN payment_order cp ON cp.order_id=o.id LEFT JOIN payment_transaction pt ON pt.order_id=o.id "
            + "LEFT JOIN refund_record cr ON cr.id=(SELECT MAX(r.id) FROM refund_record r WHERE r.order_id=o.id) ";
    private final JdbcTemplate jdbc;
    public OrderReadService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public List<Map<String, Object>> list(long userId) {
        var orders = JdbcTimes.asLocalDateTimes(jdbc.queryForList(SELECT + "WHERE o.user_id=? ORDER BY o.created_at DESC", userId));
        LocalDateTime now = LocalDateTime.now(ZoneId.of("Asia/Shanghai"));
        orders.forEach(order -> OrderStatusSummary.decorate(order, now));
        return orders;
    }

    public Map<String, Object> find(long userId, String orderNo) {
        var rows = JdbcTimes.asLocalDateTimes(jdbc.queryForList(SELECT + "WHERE o.order_no=? AND o.user_id=?", orderNo, userId));
        if (rows.isEmpty()) throw new BusinessException(404, "订单不存在或无权查看");
        Map<String, Object> order = rows.getFirst();
        OrderStatusSummary.decorate(order, LocalDateTime.now(ZoneId.of("Asia/Shanghai")));
        order.put("items", JdbcTimes.asLocalDateTimes(jdbc.queryForList(
                "SELECT oi.seat_id,s.seat_code,oi.price,oi.ticket_status,oi.checked_in_at FROM order_item oi "
                        + "JOIN seat s ON s.id=oi.seat_id WHERE oi.order_id=? ORDER BY oi.id", order.get("id"))));
        return order;
    }
}
