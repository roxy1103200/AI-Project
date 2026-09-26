package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.service.AuthService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/movies/{movieId}/reviews")
public class MovieReviewController {
    private final JdbcTemplate jdbc;
    private final AuthService auth;

    public MovieReviewController(JdbcTemplate jdbc, AuthService auth) { this.jdbc = jdbc; this.auth = auth; }

    @GetMapping
    public ApiResponse<Map<String, Object>> list(@PathVariable @Positive long movieId,
            @RequestParam(defaultValue = "1") @Min(1) @Max(10000) int page,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        requireMovie(movieId);
        Map<String, Object> result = new HashMap<>(jdbc.queryForMap(
                "SELECT COUNT(*) reviewCount, ROUND(AVG(rating),1) averageRating FROM movie_review WHERE movie_id=?", movieId));
        result.put("reviews", jdbc.queryForList("SELECT r.id,r.rating,r.content,r.created_at,r.updated_at,u.username "
                + "FROM movie_review r JOIN users u ON u.id=r.user_id WHERE r.movie_id=? "
                + "ORDER BY r.updated_at DESC,r.id DESC LIMIT 10 OFFSET ?", movieId, (page - 1) * 10));
        result.put("page", page);
        if (token != null && !token.isBlank()) {
            var own = jdbc.queryForList("SELECT id,rating,content,created_at,updated_at FROM movie_review WHERE movie_id=? AND user_id=?",
                    movieId, auth.requireUserId(token));
            result.put("ownReview", own.isEmpty() ? null : own.getFirst());
        }
        return ApiResponse.success(result);
    }

    @PutMapping
    public ApiResponse<Void> save(@PathVariable @Positive long movieId,
            @RequestHeader("X-Auth-Token") String token, @Valid @RequestBody ReviewInput input) {
        long userId = auth.requireUserId(token);
        requireMovie(movieId);
        LocalDateTime now = LocalDateTime.now();
        jdbc.update("INSERT INTO movie_review(movie_id,user_id,rating,content,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                        + "ON DUPLICATE KEY UPDATE rating=?,content=?,updated_at=?",
                movieId, userId, input.rating(), input.content().trim(), now, now,
                input.rating(), input.content().trim(), now);
        return ApiResponse.success(null);
    }

    @DeleteMapping
    public ApiResponse<Void> delete(@PathVariable @Positive long movieId, @RequestHeader("X-Auth-Token") String token) {
        jdbc.update("DELETE FROM movie_review WHERE movie_id=? AND user_id=?", movieId, auth.requireUserId(token));
        return ApiResponse.success(null);
    }

    private void requireMovie(long id) {
        if (jdbc.queryForList("SELECT id FROM movie WHERE id=?", id).isEmpty()) throw new BusinessException(404, "影片不存在");
    }

    public record ReviewInput(@Min(1) @Max(5) int rating, @NotBlank @Size(max = 1000) String content) {}
}
