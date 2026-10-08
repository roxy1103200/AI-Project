package com.cinema.ticketing.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.GlobalExceptionHandler;
import com.cinema.ticketing.controller.InternalAiController;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/** Real SQL fixtures and fixed Beijing business clock; no shared database or real accounts. */
class AiMovieQueryServiceTest {
    private static final LocalDate TODAY = LocalDate.of(2026, 10, 8);
    private JdbcTemplate jdbc;
    private AiMovieQueryService service;
    private MockMvc mvc;

    @BeforeEach
    void seed() {
        jdbc =
                new JdbcTemplate(
                        new DriverManagerDataSource(
                                "jdbc:h2:mem:"
                                        + UUID.randomUUID()
                                        + ";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1",
                                "sa",
                                ""));
        jdbc.execute(
                "CREATE TABLE movie (id BIGINT PRIMARY KEY,title VARCHAR(128),description"
                    + " VARCHAR(128),duration INT,release_date DATE,director VARCHAR(128),actors"
                    + " VARCHAR(128),genre VARCHAR(128),status VARCHAR(32),sale_start_time"
                    + " TIMESTAMP,sale_end_time TIMESTAMP)");
        jdbc.execute(
                "CREATE TABLE cinema (id BIGINT PRIMARY KEY,name VARCHAR(128),status VARCHAR(32))");
        jdbc.execute(
                "CREATE TABLE hall (id BIGINT PRIMARY KEY,cinema_id BIGINT,name VARCHAR(128),status"
                    + " VARCHAR(32))");
        jdbc.execute(
                "CREATE TABLE screening (id BIGINT AUTO_INCREMENT PRIMARY KEY,movie_id"
                    + " BIGINT,hall_id BIGINT,start_time TIMESTAMP,end_time TIMESTAMP,price"
                    + " DECIMAL(10,2),status VARCHAR(32))");
        jdbc.update("INSERT INTO cinema VALUES (1,'测试影院','ACTIVE'),(2,'停用影院','DISABLED')");
        jdbc.update(
                "INSERT INTO hall VALUES"
                    + " (1,1,'标准厅','ACTIVE'),(2,1,'停用厅','DISABLED'),(3,2,'另一影厅','ACTIVE')");
        for (int id = 1; id <= 11; id++) {
            String status =
                    Set.of(2, 11).contains(id)
                            ? "UPCOMING"
                            : id == 8 ? "OFFLINE" : id == 9 ? "ON_SHOW" : "ON_SHELF";
            LocalDate release =
                    Set.of(2, 4, 11).contains(id) ? TODAY.plusMonths(1) : TODAY.minusMonths(1);
            jdbc.update(
                    "INSERT INTO movie (id,title,duration,release_date,genre,status) VALUES"
                        + " (?,?,120,?,'科幻',?)",
                    id,
                    "测试电影" + id,
                    release,
                    status);
        }
        jdbc.update("UPDATE movie SET sale_start_time=? WHERE id IN (2,4)", TODAY.atTime(17, 0));
        slot(2, 1, TODAY + "T18:00:00", "SCHEDULED");
        slot(3, 1, TODAY + "T09:00:00", "SCHEDULED");
        slot(3, 1, TODAY + "T18:00:00", "SCHEDULED");
        slot(4, 1, TODAY + "T19:00:00", "SCHEDULED");
        slot(5, 1, TODAY + "T18:00:00", "CANCELLED");
        slot(6, 2, TODAY + "T18:00:00", "SCHEDULED");
        slot(7, 3, TODAY + "T18:00:00", "SCHEDULED");
        slot(8, 1, TODAY + "T18:00:00", "SCHEDULED");
        slot(9, 1, TODAY + "T00:00:00", "SCHEDULED");
        slot(9, 1, TODAY.minusDays(1) + "T23:59:00", "SCHEDULED");
        slot(9, 1, TODAY.plusDays(1) + "T00:00:00", "SCHEDULED");
        slot(10, 1, TODAY.plusDays(1) + "T18:00:00", "SCHEDULED");
        slot(11, 1, TODAY.minusDays(1) + "T09:00:00", "SCHEDULED");
        service =
                new AiMovieQueryService(
                        jdbc, Clock.fixed(Instant.parse("2026-10-08T08:00:00Z"), ZoneOffset.UTC));
        mvc =
                MockMvcBuilders.standaloneSetup(
                                new InternalAiController(jdbc, "fixture-token", service))
                        .setControllerAdvice(new GlobalExceptionHandler())
                        .build();
    }

    private void slot(long movie, long hall, String start, String status) {
        var time = java.time.LocalDateTime.parse(start);
        jdbc.update(
                "INSERT INTO screening (movie_id,hall_id,start_time,end_time,price,status) VALUES"
                    + " (?,?,?,?,30,?)",
                movie,
                hall,
                time,
                time.plusHours(2),
                status);
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> items(Map<String, Object> result) {
        return (List<Map<String, Object>>) result.get("items");
    }

    private Set<Long> ids(Map<String, Object> result) {
        return items(result).stream()
                .map(row -> ((Number) row.get("id")).longValue())
                .collect(Collectors.toSet());
    }

    private Map<String, Object> query(String scope, LocalDate date) {
        return service.movies("", scope, date, "", false, 1, 20);
    }

    @Test
    void showingDoesNotRequireScreeningsAndFutureReleaseDoesNotCountAsShowing() {
        assertEquals(Set.of(1L, 3L, 5L, 6L, 7L, 9L, 10L), ids(query("showing", TODAY)));
    }

    @Test
    void scheduledFilmsRequireRealPublishedScreeningsAndMayBeUpcoming() {
        assertEquals(Set.of(2L, 3L, 4L, 9L), ids(query("scheduled", TODAY)));
        assertFalse(ids(query("scheduled", TODAY)).contains(1L));
        assertTrue(ids(query("scheduled", TODAY)).contains(2L));
    }

    @Test
    void scheduledFilmsIncludePastAndNotYetSellableScreenings() {
        var result = query("scheduled", TODAY);
        var movie =
                items(result).stream()
                        .filter(row -> ((Number) row.get("id")).longValue() == 3)
                        .findFirst()
                        .orElseThrow();
        assertEquals(2L, ((Number) movie.get("screening_count")).longValue());
        var bookable = service.screenings(null, null, "", "", TODAY, "bookable", false);
        assertEquals(1, bookable.size());
        assertEquals(3L, ((Number) bookable.get(0).get("movie_id")).longValue());
    }

    @Test
    void showingAndSchedulingCanBeIntersected() {
        assertEquals(Set.of(3L, 9L), ids(service.movies("", "scheduled", TODAY, "", true, 1, 20)));
    }

    @Test
    void dateIsHalfOpenAndUndatedQueryStartsAtBeijingToday() {
        var today = service.screenings(9L, null, "", "", TODAY, "scheduled", false);
        assertEquals(1, today.size());
        assertEquals(TODAY.atStartOfDay(), today.get(0).get("start_time"));
        assertEquals(Set.of(2L, 3L, 4L, 9L, 10L), ids(query("scheduled", null)));
        assertEquals(TODAY.toString(), query("scheduled", null).get("from_date"));
        assertEquals(Set.of(9L, 10L), ids(query("scheduled", TODAY.plusDays(1))));
    }

    @Test
    void cancelledInactiveAndOfflineRecordsDoNotCreateEffectiveSchedules() {
        var ids = ids(query("scheduled", TODAY));
        assertTrue(Set.of(5L, 6L, 7L, 8L, 11L).stream().noneMatch(ids::contains));
    }

    @Test
    void filtersAndMoviePaginationDoNotLoseFilmsBehindManyScreenings() {
        for (int i = 0; i < 75; i++) slot(2, 1, TODAY + "T18:00:00", "SCHEDULED");
        var first = service.movies("", "scheduled", TODAY, "测试影院", false, 1, 1);
        assertEquals(4L, first.get("total"));
        assertEquals(Set.of(2L), ids(first));
        assertEquals(76L, items(first).get(0).get("screening_count"));
        assertEquals(true, items(first).get(0).get("screenings_truncated"));
        assertEquals(Set.of(4L), ids(service.movies("", "scheduled", TODAY, "测试影院", false, 3, 1)));
        assertEquals(
                Set.of(3L), ids(service.movies("测试电影3", "scheduled", TODAY, "测试影院", false, 1, 20)));
        assertEquals(
                0L, service.movies("", "scheduled", TODAY, "不存在的影院", false, 1, 20).get("total"));
    }

    @Test
    void repeatQueriesHaveStableMovieSetsAndSeparateEmptyBookableResults() {
        var first = query("scheduled", TODAY);
        for (int i = 0; i < 3; i++) assertEquals(first, query("scheduled", TODAY));
        jdbc.update("UPDATE movie SET sale_end_time=?", TODAY.atTime(15, 0));
        assertTrue(service.screenings(null, null, "", "", TODAY, "bookable", false).isEmpty());
        assertEquals(ids(first), ids(query("scheduled", TODAY)));
    }

    @Test
    void invalidScopesAndPaginationFailInsteadOfSilentlyChangingQuery() {
        assertThrows(BusinessException.class, () -> query("wrong", TODAY));
        assertThrows(
                BusinessException.class,
                () -> service.movies("", "scheduled", TODAY, "", false, 0, 20));
        assertThrows(
                BusinessException.class,
                () -> service.movies("", "scheduled", TODAY, "", false, 1, 1000));
        assertThrows(
                BusinessException.class,
                () -> service.screenings(null, null, "", "", TODAY, "wrong", false));
    }

    @Test
    void internalHttpContractKeepsAuthAndLegacyDefaultBookableScope() throws Exception {
        mvc.perform(get("/internal/movies/query").header("X-Internal-Token", "wrong"))
                .andExpect(status().isUnauthorized());
        mvc.perform(
                        get("/internal/movies/query")
                                .header("X-Internal-Token", "fixture-token")
                                .param("movieScope", "scheduled")
                                .param("screeningDate", TODAY.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(4))
                .andExpect(jsonPath("$.screening_date").value(TODAY.toString()));
        mvc.perform(
                        get("/internal/screenings")
                                .header("X-Internal-Token", "fixture-token")
                                .param("screeningDate", TODAY.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1));
        mvc.perform(
                        get("/internal/movies/query")
                                .header("X-Internal-Token", "fixture-token")
                                .param("screeningDate", "2026-02-30"))
                .andExpect(status().isBadRequest());
        mvc.perform(
                        get("/internal/movies/query")
                                .header("X-Internal-Token", "fixture-token")
                                .param("movieScope", "unknown"))
                .andExpect(status().isBadRequest());
    }
}
