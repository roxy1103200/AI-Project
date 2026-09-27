package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.service.AiFeedbackService;
import com.cinema.ticketing.service.AuthService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import java.util.UUID;

@RestController
public class AiFeedbackController {
    private final AiFeedbackService feedback;
    private final AuthService auth;
    private final String internalToken;

    public AiFeedbackController(AiFeedbackService feedback, AuthService auth, @Value("${ai.internal-token}") String internalToken) {
        this.feedback = feedback; this.auth = auth; this.internalToken = internalToken;
    }

    @PostMapping("/internal/ai/feedback")
    public Map<String, Boolean> save(@RequestHeader("X-Internal-Token") String token,
                                     @Valid @RequestBody AiFeedbackService.FeedbackInput input) {
        verify(token);
        feedback.save(input);
        return Map.of("saved", true);
    }

    public record SyncInput(@NotBlank String status) {}

    @PostMapping("/internal/ai/feedback/{messageId}/sync")
    public Map<String, Boolean> sync(@RequestHeader("X-Internal-Token") String token, @PathVariable UUID messageId,
                                     @Valid @RequestBody SyncInput input) {
        verify(token);
        feedback.sync(messageId.toString(), input.status());
        return Map.of("saved", true);
    }

    @GetMapping("/api/admin/ai-feedback")
    public ApiResponse<Map<String, Object>> list(@RequestHeader("X-Auth-Token") String token,
            @RequestParam(required = false) String provider, @RequestParam(required = false) String rating,
            @RequestParam(required = false) String status, @RequestParam(required = false) String reason,
            @RequestParam(required = false) String query, @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        auth.requireAdmin(token);
        return ApiResponse.success(feedback.list(provider, rating, status, reason, query, page, size));
    }

    public record ReviewInput(@NotBlank String status, @jakarta.validation.constraints.NotNull @Size(max = 1000) String note) {}

    @PutMapping("/api/admin/ai-feedback/{id}")
    public ApiResponse<Void> review(@RequestHeader("X-Auth-Token") String token, @PathVariable long id,
                                    @Valid @RequestBody ReviewInput input) {
        auth.requireAdmin(token);
        feedback.review(id, input.status(), input.note(), auth.requireUserId(token));
        return ApiResponse.success(null);
    }

    private void verify(String token) {
        if (!MessageDigest.isEqual(internalToken.getBytes(StandardCharsets.UTF_8), token.getBytes(StandardCharsets.UTF_8)))
            throw new BusinessException(401, "无效的内部服务凭证");
    }
}
