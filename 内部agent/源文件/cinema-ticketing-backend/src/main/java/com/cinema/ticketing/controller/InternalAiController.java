package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.RefundPolicyText;
import com.cinema.ticketing.service.AiMovieQueryService;
import com.cinema.ticketing.service.AiDateWindow;
import com.cinema.ticketing.service.KnowledgeSearchService;

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
import java.math.BigDecimal;
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
            @RequestParam(defaultValue = "20") int pageSize,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate releaseDateFrom,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate releaseDateTo,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate screeningDateFrom,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate screeningDateTo,
            @RequestParam(required = false) Integer screeningHourFrom,
            @RequestParam(required = false) Integer screeningHourTo) {
        verify(token);
        return movieQueries.movies(
                query, movieScope, screeningDate, cinemaQuery, showingOnly, page, pageSize,
                new AiDateWindow(releaseDateFrom, releaseDateTo, screeningDateFrom, screeningDateTo,
                        screeningHourFrom, screeningHourTo));
    }

    @GetMapping("/movies")
    public List<Map<String, Object>> movies(
            @RequestHeader("X-Internal-Token") String token,
            @RequestParam(required = false) String query) {
        verify(token);
        if (query == null || query.isBlank()) {
            return jdbcTemplate.queryForList(
                    "SELECT id, title, description, duration, release_date, director, actors,"
                            + " genre, status FROM movie WHERE status NOT IN ('OFFLINE','ARCHIVED') ORDER BY"
                            + " release_date DESC, id DESC LIMIT 20");
        }
        String keyword = "%" + query.trim() + "%";
        return jdbcTemplate.queryForList(
                "SELECT id, title, description, duration, release_date, director, actors, genre,"
                    + " status FROM movie WHERE status NOT IN ('OFFLINE','ARCHIVED') AND (title LIKE ? OR genre LIKE"
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
            @RequestParam(defaultValue = "false") boolean showingOnly,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate screeningDateFrom,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate screeningDateTo,
            @RequestParam(required = false) Integer screeningHourFrom,
            @RequestParam(required = false) Integer screeningHourTo) {
        verify(token);
        return movieQueries.screenings(
                movieId, cinemaId, movieQuery, cinemaQuery, screeningDate, queryScope, showingOnly,
                new AiDateWindow(null, null, screeningDateFrom, screeningDateTo, screeningHourFrom, screeningHourTo));
    }

    @GetMapping("/orders/{orderNo}")
    public Map<String, Object> order(
            @RequestHeader("X-Internal-Token") String token,
            @PathVariable String orderNo,
            @RequestParam long userId) {
        verify(token);
        return new com.cinema.ticketing.service.OrderReadService(jdbcTemplate).find(userId, orderNo);
    }

    @GetMapping("/refund-policy")
    public Map<String, Object> refundPolicy(@RequestHeader("X-Internal-Token") String token) {
        verify(token);
        return RefundPolicyText.normalize(jdbcTemplate.queryForMap(
                "SELECT policy_version version, content policy, cutoff_minutes, 'refund_policy'"
                    + " source FROM refund_policy WHERE enabled = TRUE ORDER BY id DESC LIMIT 1"), "policy");
    }

    @GetMapping("/knowledge/search")
    public List<Map<String, Object>> knowledgeSearch(
            @RequestHeader("X-Internal-Token") String token, @RequestParam String query) {
        verify(token);
        return new KnowledgeSearchService(jdbcTemplate).search(query);
    }

    @PostMapping({"/recommendations", "/recommendations/budget"})
    public List<Map<String, Object>> recommendations(
            @RequestHeader("X-Internal-Token") String token,
            @RequestBody(required = false) Map<String, Object> request) {
        verify(token);
        String preference =
                request == null ? null : String.valueOf(request.getOrDefault("preference", ""));
        Map<String, Object> values = request == null ? Map.of() : request;
        Object preferred = values.getOrDefault("releaseDatePreferred", false);
        if (!(preferred instanceof Boolean)) throw new BusinessException(400, "日期偏好参数无效");
        Object inclusive = values.getOrDefault("priceUpperInclusive", true);
        if (!(inclusive instanceof Boolean)) throw new BusinessException(400, "票价边界参数无效");
        return movieQueries.recommendations(preference,
                requestDate(values.get("releaseDateFrom")), requestDate(values.get("releaseDateTo")),
                Boolean.TRUE.equals(preferred),
                new AiDateWindow(null, null, requestDate(values.get("screeningDateFrom")),
                        requestDate(values.get("screeningDateTo")), requestHour(values.get("screeningHourFrom")),
                        requestHour(values.get("screeningHourTo"))),
                requestPrice(values.get("maxTicketPrice")), Boolean.TRUE.equals(inclusive),
                String.valueOf(values.getOrDefault("movieQuery", "")),
                String.valueOf(values.getOrDefault("cinemaQuery", "")));
    }

    private BigDecimal requestPrice(Object value) {
        if (value == null) return null;
        try {
            BigDecimal price = new BigDecimal(String.valueOf(value));
            if (price.signum() < 0 || price.scale() > 2 || price.compareTo(new BigDecimal("1000000")) > 0) {
                throw new NumberFormatException("out of range");
            }
            return price;
        } catch (NumberFormatException exception) {
            throw new BusinessException(400, "票价上限无效，请提供不超过两位小数的非负金额");
        }
    }

    private LocalDate requestDate(Object value) {
        if (value == null) return null;
        try {
            return LocalDate.parse(String.valueOf(value));
        } catch (java.time.DateTimeException exception) {
            throw new BusinessException(400, "日期格式无效，请使用 YYYY-MM-DD");
        }
    }

    private Integer requestHour(Object value) {
        if (value == null) return null;
        if (!(value instanceof Integer)) throw new BusinessException(400, "场次时段参数无效");
        return (Integer) value;
    }

    private void verify(String token) {
        if (!internalToken.equals(token)) {
            throw new BusinessException(401, "无效的内部服务凭证");
        }
    }
}
