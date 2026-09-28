package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.service.AiHandoffService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;

@RestController
public class AiHandoffController {
    private final AiHandoffService handoffs;
    private final String internalToken;

    public AiHandoffController(AiHandoffService handoffs, @Value("${ai.internal-token}") String internalToken) {
        this.handoffs = handoffs;
        this.internalToken = internalToken;
    }

    @PostMapping("/api/ai/handoff")
    public ApiResponse<Map<String, Object>> issue(@RequestHeader("X-Auth-Token") String authToken,
                                                 @Valid @RequestBody HandoffRequest request) {
        return ApiResponse.success(handoffs.issue(authToken, request.sessionId()));
    }

    @PostMapping("/internal/ai/handoff/resolve")
    public Map<String, Object> resolve(@RequestHeader("X-Internal-Token") String token,
                                      @Valid @RequestBody CredentialRequest request) {
        if (!MessageDigest.isEqual(internalToken.getBytes(StandardCharsets.UTF_8), token.getBytes(StandardCharsets.UTF_8))) {
            throw new BusinessException(401, "无效的内部服务凭证");
        }
        return handoffs.resolve(request.credential());
    }

    public record HandoffRequest(@NotBlank @Pattern(regexp = "[a-f0-9-]{36}") String sessionId) {}
    public record CredentialRequest(@NotBlank @Pattern(regexp = "[a-f0-9-]{72}") String credential) {}
}
