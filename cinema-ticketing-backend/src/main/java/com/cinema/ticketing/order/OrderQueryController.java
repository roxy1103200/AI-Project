package com.cinema.ticketing.order;

import com.cinema.ticketing.common.ApiResponse;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/orders")
public class OrderQueryController {

    private final JdbcTemplate jdbcTemplate;

    public OrderQueryController(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestParam(required = false) Long userId) {
        if (userId == null) {
            return ApiResponse.success(jdbcTemplate.queryForList(
                    "SELECT id, order_no, user_id, screening_id, total_amount, status, expire_at, paid_at, created_at "
                            + "FROM ticket_order ORDER BY created_at DESC"));
        }
        return ApiResponse.success(jdbcTemplate.queryForList(
                "SELECT id, order_no, user_id, screening_id, total_amount, status, expire_at, paid_at, created_at "
                        + "FROM ticket_order WHERE user_id = ? ORDER BY created_at DESC", userId));
    }

    @GetMapping("/{orderNo}")
    public ApiResponse<Map<String, Object>> find(@PathVariable String orderNo) {
        Map<String, Object> order = jdbcTemplate.queryForMap(
                "SELECT id, order_no, user_id, screening_id, total_amount, status, expire_at, paid_at, created_at "
                        + "FROM ticket_order WHERE order_no = ?", orderNo);
        return ApiResponse.success(order);
    }
}
