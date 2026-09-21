package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
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
        if (userId == null || !authService.isAdmin(token)) {
            return ApiResponse.success(jdbcTemplate.queryForList(
                    "SELECT id, order_no, user_id, screening_id, total_amount, status, expire_at, paid_at, created_at "
                            + "FROM ticket_order WHERE user_id = ? ORDER BY created_at DESC", currentUserId));
        }
        return ApiResponse.success(jdbcTemplate.queryForList(
                "SELECT id, order_no, user_id, screening_id, total_amount, status, expire_at, paid_at, created_at "
                        + "FROM ticket_order WHERE user_id = ? ORDER BY created_at DESC", userId));
    }
}
