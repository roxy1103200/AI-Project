package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.MovieReviewModerationService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/admin/movie-reviews")
public class MovieReviewAdminController {
    private final MovieReviewModerationService reviews;
    private final AuthService auth;

    public MovieReviewAdminController(MovieReviewModerationService reviews, AuthService auth) { this.reviews = reviews; this.auth = auth; }

    @GetMapping
    public ApiResponse<?> list(@RequestHeader("X-Auth-Token") String token, @RequestParam(required = false) String kind,
            @RequestParam(required = false) String status, @RequestParam(required = false) @Size(max = 120) String query,
            @RequestParam(defaultValue = "1") @Min(1) @Max(10000) int page) {
        auth.requireAdmin(token);
        return ApiResponse.success(reviews.list(kind, status, query, page));
    }

    @PutMapping("/{kind}/{id}")
    public ApiResponse<Void> moderate(@RequestHeader("X-Auth-Token") String token, @PathVariable String kind,
            @PathVariable @Positive long id, @Valid @RequestBody ModerationInput input) {
        auth.requireAdmin(token);
        reviews.moderate(kind, id, input.revision(), input.status(), input.note(), auth.requireUserId(token));
        return ApiResponse.success(null);
    }

    @GetMapping("/{kind}/{id}/history")
    public ApiResponse<?> history(@RequestHeader("X-Auth-Token") String token, @PathVariable String kind, @PathVariable @Positive long id) {
        auth.requireAdmin(token);
        return ApiResponse.success(reviews.history(kind, id));
    }

    @GetMapping("/reports")
    public ApiResponse<?> reports(@RequestHeader("X-Auth-Token") String token, @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") @Min(1) @Max(10000) int page) {
        auth.requireAdmin(token);
        return ApiResponse.success(reviews.reports(status, page));
    }

    @PutMapping("/reports/{id}")
    public ApiResponse<Void> resolve(@RequestHeader("X-Auth-Token") String token, @PathVariable @Positive long id,
            @Valid @RequestBody ReportResolution input) {
        auth.requireAdmin(token);
        reviews.resolve(id, input.status(), input.note(), input.hideTarget(), input.revision(), auth.requireUserId(token));
        return ApiResponse.success(null);
    }

    public record ModerationInput(@Positive long revision, @NotBlank String status, @Size(max = 1000) String note) {}
    public record ReportResolution(@NotBlank String status, @NotBlank @Size(max = 1000) String note, boolean hideTarget, @Positive Long revision) {}
}
