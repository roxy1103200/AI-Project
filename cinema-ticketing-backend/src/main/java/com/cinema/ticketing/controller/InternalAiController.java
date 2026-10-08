package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.JdbcTimes;
import com.cinema.ticketing.service.AiMovieQueryService;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/internal")
public class InternalAiController {

    private final JdbcTemplate jdbcTemplate;
    private final String internalToken;
    private final AiMovieQueryService movieQueries;

    public InternalAiController(JdbcTemplate jdbcTemplate, String internalToken) {
        this(jdbcTemplate, internalToken, new AiMovieQueryService(jdbcTemplate));
    }

    @Autowired
    public InternalAiController(
            JdbcTemplate jdbcTemplate,
            @Value("${ai.internal-token}") String internalToken,
            AiMovieQueryService movieQueries) {
        this.jdbcTemplate = jdbcTemplate;
        this.internalToken = internalToken;
        this.movieQueries = movieQueries;
    }

    @GetMapping("/movies/query")
    public Map<String, Object> movieList(
            @RequestHeader("X-Internal-Token") String token,
            @RequestParam(defaultValue = "") String query,
            @RequestParam(defaultValue = "catalog") String movieScope,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE)
                    LocalDate screeningDate,
            @RequestParam(defaultValue = "") String cinemaQuery,
            @RequestParam(defaultValue = "false") boolean showingOnly,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int pageSize) {
        verify(token);
        return movieQueries.movies(
                query, movieScope, screeningDate, cinemaQuery, showingOnly, page, pageSize);
    }

    @GetMapping("/movies")
    public List<Map<String, Object>> movies(
            @RequestHeader("X-Internal-Token") String token,
            @RequestParam(required = false) String query) {
        verify(token);
        if (query == null || query.isBlank()) {
            return jdbcTemplate.queryForList(
                    "SELECT id, title, description, duration, release_date, director, actors,"
                            + " genre, status FROM movie WHERE status <> 'OFFLINE' ORDER BY"
                            + " release_date DESC, id DESC LIMIT 20");
        }
        String keyword = "%" + query.trim() + "%";
        return jdbcTemplate.queryForList(
                "SELECT id, title, description, duration, release_date, director, actors, genre,"
                    + " status FROM movie WHERE status <> 'OFFLINE' AND (title LIKE ? OR genre LIKE"
                    + " ? OR actors LIKE ?) ORDER BY release_date DESC, id DESC LIMIT 20",
                keyword,
                keyword,
                keyword);
    }

    @GetMapping("/screenings")
    public List<Map<String, Object>> screenings(
            @RequestHeader("X-Internal-Token") String token,
            @RequestParam(required = false) Long movieId,
            @RequestParam(required = false) Long cinemaId,
            @RequestParam(required = false) String movieQuery,
            @RequestParam(required = false) String cinemaQuery,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE)
                    LocalDate screeningDate,
            @RequestParam(defaultValue = "bookable") String queryScope,
            @RequestParam(defaultValue = "false") boolean showingOnly) {
        verify(token);
        return movieQueries.screenings(
                movieId, cinemaId, movieQuery, cinemaQuery, screeningDate, queryScope, showingOnly);
    }

    @GetMapping("/orders/{orderNo}")
    public Map<String, Object> order(
            @RequestHeader("X-Internal-Token") String token,
            @PathVariable String orderNo,
            @RequestParam long userId) {
        verify(token);
        // created_at 是 TIMESTAMP 列（JSON 里带 +00:00 偏移），expire_at / paid_at 是 DATETIME
        // （无时区的本地字面量）。统一成 LocalDateTime 再返回，见 JdbcTimes。
        Map<String, Object> order =
                JdbcTimes.asLocalDateTimes(
                        jdbcTemplate.queryForMap(
                                "SELECT o.id, o.order_no, o.user_id, o.screening_id,"
                                    + " o.total_amount, o.status, o.expire_at, o.paid_at,"
                                    + " o.created_at, m.title movie_title, s.start_time, h.name"
                                    + " hall_name, c.name cinema_name, p.cutoff_minutes"
                                    + " refund_cutoff_minutes, EXISTS(SELECT 1 FROM order_item i"
                                    + " WHERE i.order_id=o.id AND i.checked_in_at IS NOT NULL)"
                                    + " has_check_in FROM ticket_order o JOIN screening s ON"
                                    + " s.id=o.screening_id JOIN movie m ON m.id=s.movie_id JOIN"
                                    + " hall h ON h.id=s.hall_id JOIN cinema c ON c.id=h.cinema_id"
                                    + " LEFT JOIN refund_policy p ON p.id=(SELECT MAX(id) FROM"
                                    + " refund_policy WHERE enabled=TRUE) WHERE o.order_no = ? AND"
                                    + " o.user_id = ?",
                                orderNo,
                                userId));
        Map<String, Object> result = new HashMap<>(order);
        Number cutoff = (Number) order.get("refund_cutoff_minutes");
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime deadline =
                cutoff == null
                        ? null
                        : ((LocalDateTime) order.get("start_time"))
                                .minusMinutes(cutoff.longValue());
        boolean checkedIn =
                Boolean.TRUE.equals(order.get("has_check_in"))
                        || "1".equals(String.valueOf(order.get("has_check_in")));
        boolean allowed =
                "ISSUED".equals(order.get("status"))
                        && !checkedIn
                        && deadline != null
                        && now.isBefore(deadline);
        result.put("refund_deadline", deadline);
        result.put("can_refund", allowed);
        result.put("server_time", now);
        result.put(
                "refund_reason",
                cutoff == null
                        ? "退票规则暂不可用"
                        : !"ISSUED".equals(order.get("status"))
                                ? "只有已出票订单可以退票"
                                : checkedIn
                                        ? "订单中已有电影票验票入场，不能退票"
                                        : allowed ? "当前可申请退票" : "已超过退票截止时间");
        result.put(
                "items",
                jdbcTemplate.queryForList(
                        "SELECT oi.seat_id, s.seat_code, oi.price, oi.ticket_status,"
                                + " oi.checked_in_at FROM order_item oi JOIN seat s ON s.id ="
                                + " oi.seat_id WHERE oi.order_id = ? ORDER BY oi.id",
                        order.get("id")));
        return result;
    }

    @GetMapping("/refund-policy")
    public Map<String, Object> refundPolicy(@RequestHeader("X-Internal-Token") String token) {
        verify(token);
        return jdbcTemplate.queryForMap(
                "SELECT policy_version version, content policy, cutoff_minutes, 'refund_policy'"
                    + " source FROM refund_policy WHERE enabled = TRUE ORDER BY id DESC LIMIT 1");
    }

    @GetMapping("/knowledge/search")
    public List<Map<String, Object>> knowledgeSearch(
            @RequestHeader("X-Internal-Token") String token, @RequestParam String query) {
        verify(token);
        String keyword = "%" + query.trim() + "%";
        return jdbcTemplate.queryForList(
                "SELECT id, title, content, document_type, version "
                        + "FROM knowledge_document WHERE status = 'PUBLISHED' "
                        + "AND (title LIKE ? OR content LIKE ?) ORDER BY id DESC LIMIT 10",
                keyword,
                keyword);
    }

    @PostMapping("/recommendations")
    public List<Map<String, Object>> recommendations(
            @RequestHeader("X-Internal-Token") String token,
            @RequestBody(required = false) Map<String, Object> request) {
        verify(token);
        String preference =
                request == null ? null : String.valueOf(request.getOrDefault("preference", ""));
        if (preference == null || preference.isBlank()) {
            return jdbcTemplate.queryForList(
                    "SELECT id, title, description, genre, director, actors FROM movie WHERE status"
                            + " <> 'OFFLINE' ORDER BY release_date DESC, id DESC LIMIT 5");
        }
        String keyword = "%" + preference + "%";
        return jdbcTemplate.queryForList(
                "SELECT id, title, description, genre, director, actors FROM movie WHERE status <>"
                        + " 'OFFLINE' AND (genre LIKE ? OR title LIKE ? OR actors LIKE ?) ORDER BY"
                        + " release_date DESC, id DESC LIMIT 5",
                keyword,
                keyword,
                keyword);
    }

    private void verify(String token) {
        if (!internalToken.equals(token)) {
            throw new BusinessException(401, "无效的内部服务凭证");
        }
    }
}
