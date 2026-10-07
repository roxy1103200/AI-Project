package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.dto.CurrentSession;
import com.cinema.ticketing.service.AccountSecurityService;
import com.cinema.ticketing.service.AuthService;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import java.util.Map;

@RestController
public class AccountSecurityController {
    private final AuthService auth;
    private final AccountSecurityService accounts;
    private final String internalToken;

    public AccountSecurityController(
            AuthService auth,
            AccountSecurityService accounts,
            @Value("${ai.internal-token}") String internalToken) {
        this.auth = auth;
        this.accounts = accounts;
        this.internalToken = internalToken;
    }

    @PostMapping("/api/auth/logout-all")
    public ApiResponse<Void> logoutAll(@RequestHeader("X-Auth-Token") String token) {
        auth.logoutAll(token);
        return ApiResponse.success(null);
    }

    @PostMapping("/api/auth/password")
    public ApiResponse<Void> password(
            @RequestHeader("X-Auth-Token") String token,
            @Valid @RequestBody PasswordRequest request) {
        auth.changePassword(token, request.currentPassword(), request.newPassword());
        return ApiResponse.success(null);
    }

    @GetMapping("/api/admin/accounts")
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestHeader("X-Auth-Token") String token) {
        return ApiResponse.success(accounts.list(token));
    }

    @PatchMapping("/api/admin/accounts/{id}/access")
    public ApiResponse<Void> access(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable long id,
            @Valid @RequestBody AccessRequest request) {
        accounts.updateAccess(
                token, id, request.role(), request.status(), request.sessionVersion());
        return ApiResponse.success(null);
    }

    @PostMapping("/api/admin/accounts/{id}/revoke-sessions")
    public ApiResponse<Void> revoke(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable long id,
            @Valid @RequestBody VersionRequest request) {
        accounts.revoke(token, id, request.sessionVersion());
        return ApiResponse.success(null);
    }

    /** The gateway asks Java to apply exactly the same identity rules as business requests. */
    @PostMapping("/internal/ai/auth/resolve")
    public CurrentSession resolve(
            @RequestHeader("X-Internal-Token") String token,
            @Valid @RequestBody TokenRequest request) {
        if (internalToken.isBlank()
                || !MessageDigest.isEqual(
                        internalToken.getBytes(StandardCharsets.UTF_8),
                        token.getBytes(StandardCharsets.UTF_8))) {
            throw new BusinessException(403, "内部凭证无效");
        }
        return auth.current(request.token());
    }

    public record PasswordRequest(
            @NotBlank @Size(max = 72) String currentPassword,
            @NotBlank @Size(min = 8, max = 72) String newPassword) {}

    public record AccessRequest(
            @NotBlank @Pattern(regexp = "USER|ADMIN") String role,
            @NotBlank @Pattern(regexp = "ACTIVE|DISABLED") String status,
            @NotNull @Min(0) Long sessionVersion) {}

    public record VersionRequest(@NotNull @Min(0) Long sessionVersion) {}

    public record TokenRequest(@NotBlank @Size(max = 36) String token) {}
}
