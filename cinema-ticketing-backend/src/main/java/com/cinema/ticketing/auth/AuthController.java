package com.cinema.ticketing.auth;

import com.cinema.ticketing.common.ApiResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.web.bind.annotation.PostMapping;
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
    public ApiResponse<AuthService.LoginResult> login(@Valid @RequestBody LoginRequest request) {
        return ApiResponse.success(authService.login(request.username(), request.password()));
    }

    @PostMapping("/logout")
    public ApiResponse<Void> logout(@RequestHeader("X-Auth-Token") String token) {
        authService.logout(token);
        return ApiResponse.success(null);
    }

    public record RegisterRequest(
            @NotBlank String username,
            @NotBlank @Size(min = 8, max = 72) String password,
            String phone) {
    }

    public record LoginRequest(@NotBlank String username, @NotBlank String password) {
    }

    public record PublicAccount(Long id, String username, String phone, String role) {

        private static PublicAccount from(UserAccount account) {
            return new PublicAccount(account.getId(), account.getUsername(), account.getPhone(), account.getRole());
        }
    }
}
