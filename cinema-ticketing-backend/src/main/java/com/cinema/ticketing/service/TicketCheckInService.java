package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.JdbcTimes;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Service
public class TicketCheckInService {
    private final JdbcTemplate jdbc;

    public TicketCheckInService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Map<String, Object> lookup(String orderNo) {
        Map<String, Object> order = order(orderNo, false);
        order.put("items", JdbcTimes.asLocalDateTimes(jdbc.queryForList("SELECT i.id,i.ticket_status,i.checked_in_at,i.checked_in_by,"
                + "s.seat_code FROM order_item i JOIN seat s ON s.id=i.seat_id WHERE i.order_id=? ORDER BY i.id", order.get("id"))));
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime start = JdbcTimes.asLocalDateTime(order.get("start_time"));
        LocalDateTime end = start.plusMinutes(((Number) order.get("duration")).longValue());
        boolean inWindow = !now.isBefore(start.minusMinutes(15)) && now.isBefore(end);
        order.put("canCheckIn", "ISSUED".equals(order.get("status")) && "SCHEDULED".equals(order.get("screening_status")) && inWindow);
        order.put("checkInReason", !"ISSUED".equals(order.get("status")) ? "只有已出票订单可以验票"
                : !"SCHEDULED".equals(order.get("screening_status")) ? "场次已取消"
                : !inWindow ? "验票开放时间为开场前 15 分钟至影片放映结束" : "请选择实际到场的座位验票");
        order.put("viewing_end_time", end);
        return order;
    }

    @Transactional
    public Map<String, Object> checkIn(String orderNo, List<Long> itemIds, long adminId) {
        Map<String, Object> order = order(orderNo, true);
        if (!"ISSUED".equals(order.get("status"))) throw new BusinessException(409, "只有已出票订单可以验票");
        if (!"SCHEDULED".equals(order.get("screening_status"))) throw new BusinessException(409, "场次已取消，不能验票");
        var items = jdbc.queryForList("SELECT id,ticket_status,checked_in_at FROM order_item WHERE order_id=? FOR UPDATE", order.get("id"));
        var selected = items.stream().filter(item -> itemIds.contains(((Number) item.get("id")).longValue())).toList();
        if (selected.size() != itemIds.stream().distinct().count()) throw new BusinessException(400, "所选电影票不属于这个订单");
        if (selected.stream().anyMatch(item -> !List.of("ISSUED", "VALID").contains(item.get("ticket_status"))))
            throw new BusinessException(409, "取消或退票的电影票不能验票");
        if (selected.stream().allMatch(item -> item.get("checked_in_at") != null)) return lookup(orderNo);
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime start = JdbcTimes.asLocalDateTime(order.get("start_time"));
        if (now.isBefore(start.minusMinutes(15)) || !now.isBefore(start.plusMinutes(((Number) order.get("duration")).longValue())))
            throw new BusinessException(409, "不在验票时段：开场前 15 分钟至影片放映结束");
        for (var item : selected) jdbc.update("UPDATE order_item SET checked_in_at=?,checked_in_by=? WHERE id=? AND checked_in_at IS NULL",
                now, adminId, item.get("id"));
        return lookup(orderNo);
    }

    private Map<String, Object> order(String orderNo, boolean lock) {
        var orders = JdbcTimes.asLocalDateTimes(jdbc.queryForList("SELECT o.id,o.order_no,o.status,u.username,m.title movie_title,"
                + "m.duration,s.start_time,s.status screening_status,c.name cinema_name,h.name hall_name "
                + "FROM ticket_order o JOIN users u ON u.id=o.user_id JOIN screening s ON s.id=o.screening_id "
                + "JOIN movie m ON m.id=s.movie_id JOIN hall h ON h.id=s.hall_id JOIN cinema c ON c.id=h.cinema_id "
                + "WHERE o.order_no=?" + (lock ? " FOR UPDATE" : ""), orderNo));
        if (orders.isEmpty()) throw new BusinessException(404, "订单不存在");
        return orders.getFirst();
    }
}
