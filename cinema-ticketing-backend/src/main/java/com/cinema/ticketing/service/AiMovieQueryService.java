package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.JdbcTimes;
import com.cinema.ticketing.common.SellableScreenings;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.math.BigDecimal;
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
            "s.status='SCHEDULED' AND m.status NOT IN ('OFFLINE','ARCHIVED') "
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
        return movies(query, scope, date, cinema, showingOnly, page, pageSize, AiDateWindow.EMPTY);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> movies(
            String query, String scope, LocalDate date, String cinema, boolean showingOnly,
            int page, int pageSize, AiDateWindow window) {
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
        Filter scheduled = scheduleFilter(date, cinema, now, window);
        StringBuilder where = new StringBuilder("m.status NOT IN ('OFFLINE','ARCHIVED')");
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
        appendRelease(where, args, window.releaseFrom(), window.releaseTo());
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
        result.put("release_date_from", window.releaseFrom());
        result.put("release_date_to", window.releaseTo());
        result.put("screening_date_from", window.screeningFrom());
        result.put("screening_date_to", window.screeningTo());
        result.put("screening_hour_from", window.hourFrom());
        result.put("screening_hour_to", window.hourTo());
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
        return screenings(movieId, cinemaId, movieQuery, cinemaQuery, date, scope, showingOnly, AiDateWindow.EMPTY);
    }

    public List<Map<String, Object>> screenings(
            Long movieId, Long cinemaId, String movieQuery, String cinemaQuery, LocalDate date,
            String scope, boolean showingOnly, AiDateWindow window) {
        if (!List.of("scheduled", "bookable").contains(scope))
            throw new BusinessException(400, "场次查询范围无效");
        LocalDateTime now = LocalDateTime.now(clock);
        Filter filter =
                "scheduled".equals(scope)
                        ? scheduleFilter(date, cinemaQuery, now, window)
                        : new Filter(
                                SellableScreenings.WHERE, new ArrayList<>(List.of(now, now, now)));
        StringBuilder where = new StringBuilder(filter.sql());
        List<Object> args = new ArrayList<>(filter.args());
        if ("bookable".equals(scope)) {
            appendScreeningWindow(where, args, date, window);
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

    private Filter scheduleFilter(LocalDate date, String cinema, LocalDateTime now, AiDateWindow window) {
        StringBuilder where = new StringBuilder(PUBLISHED);
        List<Object> args = new ArrayList<>();
        if (date == null && window.screeningFrom() == null) {
            where.append(" AND s.start_time>=?");
            args.add(now.toLocalDate().atStartOfDay());
        }
        appendScreeningWindow(where, args, date, window);
        appendKeyword(where, args, "c.name", cinema);
        return new Filter(where.toString(), args);
    }

    private void appendDate(StringBuilder where, List<Object> args, LocalDate date) {
        if (date == null) return;
        where.append(" AND s.start_time>=? AND s.start_time<?");
        args.add(date.atStartOfDay());
        args.add(date.plusDays(1).atStartOfDay());
    }

    private void appendScreeningWindow(StringBuilder where, List<Object> args, LocalDate date, AiDateWindow window) {
        if (window.screeningFrom() != null) {
            if (date != null && (!date.equals(window.screeningFrom()) || !date.equals(window.screeningTo()))) {
                throw new BusinessException(400, "单日与场次日期范围冲突");
            }
            where.append(" AND s.start_time>=? AND s.start_time<?");
            args.add(window.screeningFrom().atStartOfDay());
            args.add(window.screeningTo().plusDays(1).atStartOfDay());
        } else appendDate(where, args, date);
        if (window.hourFrom() != null) {
            where.append(" AND HOUR(s.start_time)>=? AND HOUR(s.start_time)<?");
            args.add(window.hourFrom());
            args.add(window.hourTo());
        }
    }

    private void appendRelease(StringBuilder where, List<Object> args, LocalDate from, LocalDate to) {
        if (from != null) {
            where.append(" AND m.release_date>=? AND m.release_date<=?");
            args.add(from);
            args.add(to);
        }
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> recommendations(
            String preference, LocalDate from, LocalDate to, boolean preferred) {
        return recommendations(preference, from, to, preferred, AiDateWindow.EMPTY);
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> recommendations(
            String preference, LocalDate from, LocalDate to, boolean preferred, AiDateWindow viewing) {
        return recommendations(preference, from, to, preferred, viewing, null, true, "", "");
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> recommendations(
            String preference, LocalDate from, LocalDate to, boolean preferred, AiDateWindow viewing,
            BigDecimal maxTicketPrice, boolean priceUpperInclusive, String movieQuery, String cinemaQuery) {
        new AiDateWindow(from, to, null, null, null, null);
        if (maxTicketPrice != null && (maxTicketPrice.signum() < 0 || maxTicketPrice.scale() > 2
                || maxTicketPrice.compareTo(new BigDecimal("1000000")) > 0)) {
            throw new BusinessException(400, "票价上限无效，请提供不超过两位小数的非负金额");
        }
        StringBuilder where = new StringBuilder("m.status NOT IN ('OFFLINE','ARCHIVED')");
        List<Object> args = new ArrayList<>();
        Filter screeningFilter = null;
        if (viewing.screeningFrom() != null || viewing.hourFrom() != null || maxTicketPrice != null
                || (cinemaQuery != null && !cinemaQuery.isBlank())) {
            LocalDateTime now = LocalDateTime.now(clock);
            StringBuilder sql = new StringBuilder(SellableScreenings.WHERE);
            List<Object> slots = new ArrayList<>(List.of(now, now, now));
            appendScreeningWindow(sql, slots, null, viewing);
            if (maxTicketPrice != null) {
                sql.append(" AND s.price>=0");
                sql.append(priceUpperInclusive ? " AND s.price<=?" : " AND s.price<?");
                slots.add(maxTicketPrice);
            }
            appendKeyword(sql, slots, "c.name", cinemaQuery);
            screeningFilter = new Filter(sql.toString(), slots);
            where.append(" AND EXISTS (SELECT 1 FROM screening s JOIN hall h ON h.id=s.hall_id"
                    + " JOIN cinema c ON c.id=h.cinema_id WHERE s.movie_id=m.id AND ")
                    .append(screeningFilter.sql()).append(")");
            args.addAll(slots);
        }
        if (preference != null && !preference.isBlank()) {
            where.append(" AND (m.genre LIKE ? OR m.title LIKE ? OR m.actors LIKE ?)");
            String keyword = "%" + preference.trim() + "%";
            args.addAll(List.of(keyword, keyword, keyword));
        }
        appendKeyword(where, args, "m.title", movieQuery);
        if (!preferred) appendRelease(where, args, from, to);
        String ordering = "";
        if (preferred && from != null) {
            ordering = "CASE WHEN m.release_date>=? AND m.release_date<=? THEN 0 ELSE 1 END,";
            args.add(from);
            args.add(to);
        }
        var rows = jdbc.queryForList(
                "SELECT m.id,m.title,m.description,m.duration,m.genre,m.director,m.actors,m.release_date"
                        + " FROM movie m WHERE " + where + " ORDER BY " + ordering
                        + " m.release_date DESC,m.id DESC LIMIT 5", args.toArray());
        if (screeningFilter != null && !rows.isEmpty()) attachScreenings(rows, screeningFilter);
        for (var row : rows) {
            Object raw = row.get("release_date");
            LocalDate released = raw == null ? null : LocalDate.parse(raw.toString());
            if (released != null) row.put("release_date", released.toString());
            if (from != null) row.put("matches_release_window",
                    released != null && !released.isBefore(from) && !released.isAfter(to));
        }
        return rows;
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
