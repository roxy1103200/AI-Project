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
        if (userId == null || !authService.isAdmin(token)) {
            return ApiResponse.success(JdbcTimes.asLocalDateTimes(jdbcTemplate.queryForList(
                    "SELECT id, order_no, user_id, screening_id, total_amount, status, expire_at, paid_at, created_at "
                            + "FROM ticket_order WHERE user_id = ? ORDER BY created_at DESC", currentUserId)));
        }
        return ApiResponse.success(JdbcTimes.asLocalDateTimes(jdbcTemplate.queryForList(
                "SELECT id, order_no, user_id, screening_id, total_amount, status, expire_at, paid_at, created_at "
                        + "FROM ticket_order WHERE user_id = ? ORDER BY created_at DESC", userId)));
    }
}
