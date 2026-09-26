package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.common.JdbcTimes;
import com.cinema.ticketing.service.AuthService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.time.LocalDateTime;

@RestController
@RequestMapping("/api/orders")
public class OrderQueryController {

    private final JdbcTemplate jdbcTemplate;
    private final AuthService authService;

    public OrderQueryController(JdbcTemplate jdbcTemplate, AuthService authService) {
        this.jdbcTemplate = jdbcTemplate;
        this.authService = authService;
    }

    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestHeader("X-Auth-Token") String token,
            @RequestParam(required = false) Long userId) {
        long currentUserId = authService.requireUserId(token);
        // created_at 是 TIMESTAMP 列，驱动返回 java.sql.Timestamp（JSON 里带 +00:00 偏移），
        // 而同一条记录里的 expire_at / paid_at 是 DATETIME（无时区的本地字面量）。统一成
        // LocalDateTime 再返回，见 JdbcTimes。
        long ownerId = userId != null && authService.isAdmin(token) ? userId : currentUserId;
        List<Map<String, Object>> orders = JdbcTimes.asLocalDateTimes(jdbcTemplate.queryForList(
                "SELECT o.id, o.order_no, o.user_id, o.screening_id, o.total_amount, o.status, "
                        + "o.expire_at, o.paid_at, o.created_at, m.title movie_title, "
                        + "s.start_time, h.name hall_name, c.name cinema_name, p.cutoff_minutes refund_cutoff_minutes "
                        + "FROM ticket_order o JOIN screening s ON s.id = o.screening_id "
                        + "JOIN movie m ON m.id = s.movie_id JOIN hall h ON h.id = s.hall_id "
                        + "JOIN cinema c ON c.id = h.cinema_id "
                        + "LEFT JOIN refund_policy p ON p.id=(SELECT MAX(id) FROM refund_policy WHERE enabled=TRUE) "
                        + "WHERE o.user_id = ? ORDER BY o.created_at DESC", ownerId));
        LocalDateTime now = LocalDateTime.now();
        for (Map<String, Object> order : orders) {
            Number cutoff = (Number) order.get("refund_cutoff_minutes");
            LocalDateTime deadline = cutoff == null ? null
                    : ((LocalDateTime) order.get("start_time")).minusMinutes(cutoff.longValue());
            boolean allowed = "ISSUED".equals(order.get("status")) && deadline != null && now.isBefore(deadline);
            order.put("refund_deadline", deadline);
            order.put("can_refund", allowed);
            order.put("server_time", now);
            order.put("refund_reason", cutoff == null ? "退票规则暂不可用" : !"ISSUED".equals(order.get("status"))
                    ? "只有已出票订单可以退票" : !allowed ? "已超过退票截止时间" : "");
        }
        return ApiResponse.success(orders);
    }
}
