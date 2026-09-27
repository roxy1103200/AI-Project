package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.dto.LoginRequest;
import com.cinema.ticketing.dto.LoginResult;
import com.cinema.ticketing.dto.CurrentSession;
import com.cinema.ticketing.dto.PublicAccount;
import com.cinema.ticketing.dto.RegisterRequest;
import com.cinema.ticketing.entity.UserAccount;
import com.cinema.ticketing.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/register")
    public ApiResponse<PublicAccount> register(@Valid @RequestBody RegisterRequest request) {
        UserAccount account = authService.register(request.username(), request.password(), request.phone());
        return ApiResponse.success(PublicAccount.from(account));
    }

    @PostMapping("/login")
    public ApiResponse<LoginResult> login(@Valid @RequestBody LoginRequest request) {
        return ApiResponse.success(authService.login(request.username(), request.password()));
    }

    @GetMapping("/me")
    public ApiResponse<CurrentSession> current(@RequestHeader("X-Auth-Token") String token) {
        return ApiResponse.success(authService.current(token));
    }

    @PostMapping("/logout")
    public ApiResponse<Void> logout(@RequestHeader("X-Auth-Token") String token) {
        authService.logout(token);
        return ApiResponse.success(null);
    }
}
