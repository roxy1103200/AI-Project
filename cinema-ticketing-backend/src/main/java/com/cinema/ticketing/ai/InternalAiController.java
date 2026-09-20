package com.cinema.ticketing.ai;

import com.cinema.ticketing.common.BusinessException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/internal")
public class InternalAiController {

    private final JdbcTemplate jdbcTemplate;
    private final String internalToken;

    public InternalAiController(JdbcTemplate jdbcTemplate,
                                @Value("${ai.internal-token}") String internalToken) {
        this.jdbcTemplate = jdbcTemplate;
        this.internalToken = internalToken;
    }

    @GetMapping("/movies")
    public List<Map<String, Object>> movies(@RequestHeader("X-Internal-Token") String token,
                                            @RequestParam(required = false) String query) {
        verify(token);
        if (query == null || query.isBlank()) {
            return jdbcTemplate.queryForList("SELECT id, title, description, duration, release_date, director, actors, genre, status "
                    + "FROM movie WHERE status <> 'OFFLINE' ORDER BY release_date DESC, id DESC LIMIT 20");
        }
        String keyword = "%" + query.trim() + "%";
        return jdbcTemplate.queryForList("SELECT id, title, description, duration, release_date, director, actors, genre, status "
                + "FROM movie WHERE status <> 'OFFLINE' AND (title LIKE ? OR genre LIKE ? OR actors LIKE ?) "
                + "ORDER BY release_date DESC, id DESC LIMIT 20", keyword, keyword, keyword);
    }

    @GetMapping("/screenings")
    public List<Map<String, Object>> screenings(@RequestHeader("X-Internal-Token") String token,
                                                @RequestParam(required = false) Long movieId,
                                                @RequestParam(required = false) Long cinemaId) {
        verify(token);
        StringBuilder sql = new StringBuilder("SELECT s.id, s.movie_id, m.title, s.hall_id, h.name hall_name, "
                + "c.id cinema_id, c.name cinema_name, s.start_time, s.end_time, s.price, s.status "
                + "FROM screening s JOIN movie m ON m.id = s.movie_id JOIN hall h ON h.id = s.hall_id "
                + "JOIN cinema c ON c.id = h.cinema_id WHERE s.status = 'SCHEDULED'");
        List<Object> parameters = new ArrayList<>();
        if (movieId != null) {
            sql.append(" AND s.movie_id = ?");
            parameters.add(movieId);
        }
        if (cinemaId != null) {
            sql.append(" AND c.id = ?");
            parameters.add(cinemaId);
        }
        sql.append(" ORDER BY s.start_time LIMIT 50");
        return jdbcTemplate.queryForList(sql.toString(), parameters.toArray());
    }

    @GetMapping("/orders/{orderNo}")
    public Map<String, Object> order(@RequestHeader("X-Internal-Token") String token,
                                     @PathVariable String orderNo,
                                     @RequestParam long userId) {
        verify(token);
        Map<String, Object> order = jdbcTemplate.queryForMap(
                "SELECT id, order_no, user_id, screening_id, total_amount, status, expire_at, paid_at, created_at "
                        + "FROM ticket_order WHERE order_no = ? AND user_id = ?", orderNo, userId);
        Map<String, Object> result = new HashMap<>(order);
        result.put("items", jdbcTemplate.queryForList(
                "SELECT oi.seat_id, s.seat_code, oi.price, oi.ticket_status FROM order_item oi "
                        + "JOIN seat s ON s.id = oi.seat_id WHERE oi.order_id = ? ORDER BY oi.id", order.get("id")));
        return result;
    }

    @GetMapping("/refund-policy")
    public Map<String, Object> refundPolicy(@RequestHeader("X-Internal-Token") String token) {
        verify(token);
        return jdbcTemplate.queryForMap("SELECT policy_version version, content policy, cutoff_minutes, "
                + "'refund_policy' source FROM refund_policy WHERE enabled = TRUE ORDER BY id DESC LIMIT 1");
    }

    @GetMapping("/knowledge/search")
    public List<Map<String, Object>> knowledgeSearch(@RequestHeader("X-Internal-Token") String token,
                                                     @RequestParam String query) {
        verify(token);
        String keyword = "%" + query.trim() + "%";
        return jdbcTemplate.queryForList("SELECT id, title, content, document_type, version "
                + "FROM knowledge_document WHERE status = 'PUBLISHED' "
                + "AND (title LIKE ? OR content LIKE ?) ORDER BY id DESC LIMIT 10", keyword, keyword);
    }

    @PostMapping("/recommendations")
    public List<Map<String, Object>> recommendations(@RequestHeader("X-Internal-Token") String token,
                                                     @RequestBody(required = false) Map<String, Object> request) {
        verify(token);
        String preference = request == null ? null : String.valueOf(request.getOrDefault("preference", ""));
        if (preference == null || preference.isBlank()) {
            return jdbcTemplate.queryForList("SELECT id, title, description, genre, director, actors FROM movie "
                    + "WHERE status <> 'OFFLINE' ORDER BY release_date DESC, id DESC LIMIT 5");
        }
        String keyword = "%" + preference + "%";
        return jdbcTemplate.queryForList("SELECT id, title, description, genre, director, actors FROM movie "
                + "WHERE status <> 'OFFLINE' AND (genre LIKE ? OR title LIKE ? OR actors LIKE ?) "
                + "ORDER BY release_date DESC, id DESC LIMIT 5", keyword, keyword, keyword);
    }

    private void verify(String token) {
        if (!internalToken.equals(token)) {
            throw new BusinessException(401, "无效的内部服务凭证");
        }
    }
}
