package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.JdbcTimes;
import com.cinema.ticketing.common.SellableScreenings;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/** Showing is a movie property; scheduling requires actual published cinema screenings. */
@Service
public class AiMovieQueryService {
    private static final ZoneId BEIJING = ZoneId.of("Asia/Shanghai");
    private static final String JOINS =
            " FROM screening s JOIN movie m ON m.id=s.movie_id "
                    + "JOIN hall h ON h.id=s.hall_id JOIN cinema c ON c.id=h.cinema_id ";
    private static final String PUBLISHED =
            "s.status='SCHEDULED' AND m.status<>'OFFLINE' "
                    + "AND h.status='ACTIVE' AND c.status='ACTIVE'";
    private static final int DETAIL_LIMIT = 2000;
    private final JdbcTemplate jdbc;
    private final Clock clock;

    @Autowired
    public AiMovieQueryService(JdbcTemplate jdbc) {
        this(jdbc, Clock.system(BEIJING));
    }

    public AiMovieQueryService(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock.withZone(BEIJING);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> movies(
            String query,
            String scope,
            LocalDate date,
            String cinema,
            boolean showingOnly,
            int page,
            int pageSize) {
        if (!List.of("catalog", "showing", "scheduled").contains(scope)
                || page < 1
                || page > 10000
                || pageSize < 1
                || pageSize > 50) {
            throw new BusinessException(400, "影片查询范围或分页参数无效");
        }
        if (!"scheduled".equals(scope) && (showingOnly || (cinema != null && !cinema.isBlank()))) {
            throw new BusinessException(400, "影院和上映交集条件仅用于排期电影查询");
        }
        LocalDateTime now = LocalDateTime.now(clock);
        LocalDate effectiveDate = date == null ? now.toLocalDate() : date;
        Filter scheduled = scheduleFilter(date, cinema, now);
        StringBuilder where = new StringBuilder("m.status<>'OFFLINE'");
        List<Object> args = new ArrayList<>();
        if ("showing".equals(scope) || showingOnly) {
            where.append(
                    " AND m.status IN ('ON_SHELF','ON_SHOW') AND (m.release_date IS NULL OR"
                            + " m.release_date<=?)");
            args.add(effectiveDate);
        }
        if (query != null && !query.isBlank()) {
            where.append(" AND (m.title LIKE ? OR m.genre LIKE ? OR m.actors LIKE ?)");
            String keyword = "%" + query.trim() + "%";
            args.add(keyword);
            args.add(keyword);
            args.add(keyword);
        }
        if ("scheduled".equals(scope)) {
            where.append(
                            " AND EXISTS (SELECT 1 FROM screening s JOIN hall h ON h.id=s.hall_id"
                                + " JOIN cinema c ON c.id=h.cinema_id WHERE s.movie_id=m.id AND ")
                    .append(scheduled.sql())
                    .append(")");
            args.addAll(scheduled.args());
        }
        long total =
                jdbc.queryForObject(
                        "SELECT COUNT(*) FROM movie m WHERE " + where, Long.class, args.toArray());
        List<Object> pageArgs = new ArrayList<>(args);
        pageArgs.add(pageSize);
        pageArgs.add((page - 1) * pageSize);
        var items =
                jdbc.queryForList(
                        "SELECT m.id,m.title,m.description,m.duration,m.release_date,"
                                + "m.director,m.actors,m.genre,m.status FROM movie m WHERE "
                                + where
                                + " ORDER BY m.id LIMIT ? OFFSET ?",
                        pageArgs.toArray());
        if ("scheduled".equals(scope) && !items.isEmpty()) attachScreenings(items, scheduled);
        Map<String, Object> result = new HashMap<>();
        result.put("movie_scope", scope);
        result.put("showing_only", showingOnly);
        result.put("screening_date", date == null ? "" : date.toString());
        result.put("from_date", effectiveDate.toString());
        result.put("time_zone", "Asia/Shanghai");
        result.put("page", page);
        result.put("page_size", pageSize);
        result.put("total", total);
        result.put("has_more", (long) page * pageSize < total);
        result.put("items", items);
        return result;
    }

    public List<Map<String, Object>> screenings(
            Long movieId,
            Long cinemaId,
            String movieQuery,
            String cinemaQuery,
            LocalDate date,
            String scope,
            boolean showingOnly) {
        if (!List.of("scheduled", "bookable").contains(scope))
            throw new BusinessException(400, "场次查询范围无效");
        LocalDateTime now = LocalDateTime.now(clock);
        Filter filter =
                "scheduled".equals(scope)
                        ? scheduleFilter(date, cinemaQuery, now)
                        : new Filter(
                                SellableScreenings.WHERE, new ArrayList<>(List.of(now, now, now)));
        StringBuilder where = new StringBuilder(filter.sql());
        List<Object> args = new ArrayList<>(filter.args());
        if ("bookable".equals(scope)) {
            appendDate(where, args, date);
            appendKeyword(where, args, "c.name", cinemaQuery);
        }
        if (movieId != null) {
            where.append(" AND s.movie_id=?");
            args.add(movieId);
        }
        if (cinemaId != null) {
            where.append(" AND c.id=?");
            args.add(cinemaId);
        }
        appendKeyword(where, args, "m.title", movieQuery);
        if (showingOnly) {
            where.append(
                    " AND m.status IN ('ON_SHELF','ON_SHOW') AND (m.release_date IS NULL OR"
                            + " m.release_date<=?)");
            args.add(date == null ? now.toLocalDate() : date);
        }
        return JdbcTimes.asLocalDateTimes(
                jdbc.queryForList(
                        "SELECT s.id,s.movie_id,m.title,s.hall_id,h.name hall_name,c.id"
                                + " cinema_id,c.name"
                                + " cinema_name,s.start_time,s.end_time,s.price,s.status"
                                + JOINS
                                + " WHERE "
                                + where
                                + " ORDER BY s.start_time,s.id LIMIT 50",
                        args.toArray()));
    }

    private Filter scheduleFilter(LocalDate date, String cinema, LocalDateTime now) {
        StringBuilder where = new StringBuilder(PUBLISHED);
        List<Object> args = new ArrayList<>();
        if (date == null) {
            where.append(" AND s.start_time>=?");
            args.add(now.toLocalDate().atStartOfDay());
        } else appendDate(where, args, date);
        appendKeyword(where, args, "c.name", cinema);
        return new Filter(where.toString(), args);
    }

    private void appendDate(StringBuilder where, List<Object> args, LocalDate date) {
        if (date == null) return;
        where.append(" AND s.start_time>=? AND s.start_time<?");
        args.add(date.atStartOfDay());
        args.add(date.plusDays(1).atStartOfDay());
    }

    private void appendKeyword(
            StringBuilder where, List<Object> args, String column, String query) {
        if (query == null || query.isBlank()) return;
        where.append(" AND ").append(column).append(" LIKE ?");
        args.add("%" + query.trim() + "%");
    }

    private void attachScreenings(List<Map<String, Object>> movies, Filter filter) {
        // Page movies before reading details: one busy film cannot hide other scheduled films.
        String marks = movies.stream().map(movie -> "?").collect(Collectors.joining(","));
        List<Object> args = new ArrayList<>(filter.args());
        movies.forEach(movie -> args.add(movie.get("id")));
        String where = filter.sql() + " AND s.movie_id IN (" + marks + ")";
        var counts =
                jdbc.queryForList(
                        "SELECT s.movie_id,COUNT(*) screening_count"
                                + JOINS
                                + " WHERE "
                                + where
                                + " GROUP BY s.movie_id",
                        args.toArray());
        var details =
                JdbcTimes.asLocalDateTimes(
                        jdbc.queryForList(
                                "SELECT s.id,s.movie_id,s.start_time,s.end_time,"
                                        + "s.price,h.name hall_name,c.name cinema_name"
                                        + JOINS
                                        + " WHERE "
                                        + where
                                        + " ORDER BY s.start_time,s.id LIMIT "
                                        + DETAIL_LIMIT,
                                args.toArray()));
        for (var movie : movies) {
            long id = ((Number) movie.get("id")).longValue();
            long count =
                    counts.stream()
                            .filter(row -> ((Number) row.get("movie_id")).longValue() == id)
                            .mapToLong(row -> ((Number) row.get("screening_count")).longValue())
                            .findFirst()
                            .orElse(0);
            var slots =
                    details.stream()
                            .filter(row -> ((Number) row.get("movie_id")).longValue() == id)
                            .toList();
            movie.put("screening_count", count);
            movie.put("screenings", slots.stream().limit(10).toList());
            movie.put("screenings_truncated", count > Math.min(10, slots.size()));
        }
    }

    private record Filter(String sql, List<Object> args) {}
}
