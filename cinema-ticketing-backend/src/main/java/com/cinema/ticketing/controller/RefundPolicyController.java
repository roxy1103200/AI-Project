package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.service.AuthService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api/admin/refund-policy")
public class RefundPolicyController {
    private final JdbcTemplate jdbc;
    private final AuthService auth;

    public RefundPolicyController(JdbcTemplate jdbc, AuthService auth) { this.jdbc = jdbc; this.auth = auth; }

    @GetMapping
    public ApiResponse<Map<String, Object>> current(@RequestHeader("X-Auth-Token") String token) {
        auth.requireAdmin(token);
        var rows = jdbc.queryForList("SELECT id,policy_version,cutoff_minutes,content FROM refund_policy WHERE enabled=TRUE ORDER BY id DESC LIMIT 1");
        if (rows.isEmpty()) throw new BusinessException(503, "当前没有启用的退票规则");
        return ApiResponse.success(rows.getFirst());
    }

    @PutMapping
    @Transactional
    public ApiResponse<Void> update(@RequestHeader("X-Auth-Token") String token, @Valid @RequestBody PolicyInput input) {
        auth.requireAdmin(token);
        jdbc.queryForList("SELECT id FROM refund_policy ORDER BY id FOR UPDATE");
        jdbc.update("UPDATE refund_policy SET enabled=FALSE WHERE enabled=TRUE");
        jdbc.update("INSERT INTO refund_policy(policy_version,cutoff_minutes,content,enabled) VALUES(?,?,?,TRUE)",
                UUID.randomUUID().toString().replace("-", ""), input.cutoffMinutes(), input.content().trim());
        return ApiResponse.success(null);
    }

    public record PolicyInput(@Min(0) int cutoffMinutes, @NotBlank @Size(max = 1000) String content) {}
}
