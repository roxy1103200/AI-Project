package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.MovieReviewService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/movies/{movieId}/reviews")
public class MovieReviewController {
    private final MovieReviewService reviews;
    private final AuthService auth;

    public MovieReviewController(MovieReviewService reviews, AuthService auth) {
        this.reviews = reviews;
        this.auth = auth;
    }

    @GetMapping
    public ApiResponse<Map<String, Object>> list(@PathVariable @Positive long movieId,
            @RequestParam(defaultValue = "1") @Min(1) @Max(10000) int page,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        return ApiResponse.success(reviews.list(movieId, page, optionalUser(token)));
    }

    @PutMapping
    public ApiResponse<Void> save(@PathVariable @Positive long movieId,
            @RequestHeader("X-Auth-Token") String token, @Valid @RequestBody ReviewInput input) {
        reviews.save(movieId, auth.requireUserId(token), input.rating(), input.content());
        return ApiResponse.success(null);
    }

    @DeleteMapping
    public ApiResponse<Void> delete(@PathVariable @Positive long movieId, @RequestHeader("X-Auth-Token") String token) {
        reviews.delete(movieId, auth.requireUserId(token));
        return ApiResponse.success(null);
    }

    @PutMapping("/{reviewId}/like")
    public ApiResponse<Void> like(@PathVariable @Positive long movieId, @PathVariable @Positive long reviewId,
            @RequestHeader("X-Auth-Token") String token, @Valid @RequestBody LikeInput input) {
        reviews.like(movieId, reviewId, auth.requireUserId(token), input.liked());
        return ApiResponse.success(null);
    }

    @PostMapping("/{reviewId}/reports")
    public ApiResponse<Void> report(@PathVariable @Positive long movieId, @PathVariable @Positive long reviewId,
            @RequestHeader("X-Auth-Token") String token, @Valid @RequestBody ReportInput input) {
        reviews.report(movieId, reviewId, null, auth.requireUserId(token), input.reason(), input.content());
        return ApiResponse.success(null);
    }

    @GetMapping("/{reviewId}/replies")
    public ApiResponse<Map<String, Object>> replies(@PathVariable @Positive long movieId, @PathVariable @Positive long reviewId,
            @RequestParam(defaultValue = "1") @Min(1) @Max(10000) int page,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        return ApiResponse.success(reviews.replies(movieId, reviewId, page, optionalUser(token)));
    }

    @PostMapping("/{reviewId}/replies")
    public ApiResponse<Void> reply(@PathVariable @Positive long movieId, @PathVariable @Positive long reviewId,
            @RequestHeader("X-Auth-Token") String token, @Valid @RequestBody ReplyInput input) {
        reviews.reply(movieId, reviewId, auth.requireUserId(token), input.content());
        return ApiResponse.success(null);
    }

    @DeleteMapping("/{reviewId}/replies/{replyId}")
    public ApiResponse<Void> deleteReply(@PathVariable @Positive long movieId, @PathVariable @Positive long reviewId,
            @PathVariable @Positive long replyId, @RequestHeader("X-Auth-Token") String token) {
        reviews.deleteReply(movieId, reviewId, replyId, auth.requireUserId(token));
        return ApiResponse.success(null);
    }

    @PostMapping("/{reviewId}/replies/{replyId}/reports")
    public ApiResponse<Void> reportReply(@PathVariable @Positive long movieId, @PathVariable @Positive long reviewId,
            @PathVariable @Positive long replyId, @RequestHeader("X-Auth-Token") String token,
            @Valid @RequestBody ReportInput input) {
        reviews.report(movieId, reviewId, replyId, auth.requireUserId(token), input.reason(), input.content());
        return ApiResponse.success(null);
    }

    private Long optionalUser(String token) {
        return token == null || token.isBlank() ? null : auth.requireUserId(token);
    }

    public record ReviewInput(@Min(1) @Max(5) int rating, @NotBlank @Size(max = 1000) String content) {}
    public record ReplyInput(@NotBlank @Size(max = 1000) String content) {}
    public record LikeInput(@NotNull Boolean liked) {}
    public record ReportInput(@NotBlank String reason, @NotNull @Size(max = 1000) String content) {}
}
