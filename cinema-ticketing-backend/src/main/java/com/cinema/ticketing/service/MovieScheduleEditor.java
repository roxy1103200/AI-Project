package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;

/** Called inside the movie save transaction so metadata and schedules succeed together. */
final class MovieScheduleEditor {
    private final JdbcTemplate jdbc;

    MovieScheduleEditor(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    long create(Map<String, Object> values) {
        long movieId = movieId(values.get("movie_id"));
        List<Map<String, Object>> rows = lockedRows(movieId);
        Map<String, Object> created = new HashMap<>(values);
        created.remove("id");
        rows.add(created);
        return save(movieId, rows).getFirst();
    }

    void update(long id, Map<String, Object> values) {
        long movieId = screeningMovie(id);
        if (movieId(values.get("movie_id")) != movieId) throw new BusinessException(400, "场次不能更换所属影片，请新建场次");
        List<Map<String, Object>> rows = lockedRows(movieId);
        Map<String, Object> replacement = new HashMap<>(values);
        replacement.put("id", id);
        boolean found = rows.removeIf(row -> ((Number) row.get("id")).longValue() == id);
        if (!found) throw new BusinessException(404, "场次不存在");
        rows.add(replacement);
        save(movieId, rows);
    }

    void delete(long id) {
        long movieId = screeningMovie(id);
        List<Map<String, Object>> rows = lockedRows(movieId);
        if (!rows.removeIf(row -> ((Number) row.get("id")).longValue() == id)) throw new BusinessException(404, "场次不存在");
        save(movieId, rows);
    }

    private long movieId(Object value) {
        try { long id = Long.parseLong(String.valueOf(value)); if (id > 0) return id; }
        catch (NumberFormatException ignored) { }
        throw new BusinessException(400, "场次必须指定有效的影片编号");
    }

    private long screeningMovie(long id) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT movie_id FROM screening WHERE id=?", id);
        if (rows.isEmpty()) throw new BusinessException(404, "场次不存在");
        return ((Number) rows.getFirst().get("movie_id")).longValue();
    }

    private List<Map<String, Object>> lockedRows(long movieId) {
        if (jdbc.queryForList("SELECT id FROM movie WHERE id=? FOR UPDATE", movieId).isEmpty()) throw new BusinessException(404, "影片不存在");
        return new ArrayList<>(jdbc.queryForList("SELECT id,hall_id,start_time,end_time,price,status FROM screening WHERE movie_id=? ORDER BY id FOR UPDATE", movieId));
    }

    List<Long> save(long movieId, Object input) {
        List<Long> createdIds = new ArrayList<>();
        if (!(input instanceof List<?> rows) || rows.size() > 100) {
            throw new BusinessException(400, "场次必须是数组，单次最多保存 100 个场次");
        }
        Map<String, Object> movie = jdbc.queryForMap("SELECT duration, sale_start_time, sale_end_time FROM movie WHERE id=? FOR UPDATE", movieId);
        List<Slot> slots = rows.stream().map(this::parse).toList();
        Map<Long, Map<String, Object>> existing = new HashMap<>();
        for (var row : jdbc.queryForList("SELECT id, hall_id, start_time, end_time, price, status FROM screening WHERE movie_id=? FOR UPDATE", movieId)) {
            existing.put(((Number) row.get("id")).longValue(), row);
        }
        Set<Long> retained = new HashSet<>();
        Set<Long> halls = new TreeSet<>();
        for (Slot slot : slots) halls.add(slot.hallId());
        for (var row : existing.values()) halls.add(((Number) row.get("hall_id")).longValue());
        for (long hallId : halls) {
            if (jdbc.queryForList("SELECT id FROM hall WHERE id=? FOR UPDATE", hallId).isEmpty()) {
                throw new BusinessException(400, "影厅不存在");
            }
        }
        for (Slot slot : slots) {
            Map<String, Object> old = slot.id() == null ? null : existing.get(slot.id());
            if (slot.id() != null && (old == null || !retained.add(slot.id()))) {
                throw new BusinessException(400, "场次不属于当前影片或提交了重复场次");
            }
            if (old != null && unchanged(slot, old)) continue;
            if (old != null && hasOrders(slot.id())) throw new BusinessException(409, "场次已有订单，不能修改影厅、时间、票价或状态");
            validate(slot, movie);
        }
        for (long oldId : existing.keySet()) {
            if (!retained.contains(oldId)) {
                if (hasOrders(oldId)) throw new BusinessException(409, "场次已有订单，不能删除");
                jdbc.update("DELETE FROM screening WHERE id=? AND movie_id=?", oldId, movieId);
            }
        }
        // Remove old intervals before checking the submitted replacement intervals.
        for (Slot slot : slots) {
            if (slot.id() != null && !unchanged(slot, existing.get(slot.id()))) {
                jdbc.update("UPDATE screening SET status='CANCELLED' WHERE id=?", slot.id());
            }
        }
        for (Slot slot : slots) {
            if (slot.id() != null && unchanged(slot, existing.get(slot.id()))) continue;
            if ("SCHEDULED".equals(slot.status())) {
                Integer overlaps = jdbc.queryForObject("SELECT COUNT(*) FROM screening s JOIN movie m ON m.id=s.movie_id "
                        + "WHERE s.hall_id=? AND s.status='SCHEDULED' AND s.start_time < ? "
                        + "AND GREATEST(s.end_time, DATE_ADD(s.start_time, INTERVAL (m.duration+20) MINUTE)) > ? "
                        + "AND (? IS NULL OR s.id<>?)",
                        Integer.class, slot.hallId(), slot.end(), slot.start(), slot.id(), slot.id());
                if (overlaps != null && overlaps > 0) throw new BusinessException(409, "影厅在所选时间已有场次，请调整影厅或放映时间");
            }
            if (slot.id() == null) {
                GeneratedKeyHolder key = new GeneratedKeyHolder();
                jdbc.update(connection -> {
                    var statement = connection.prepareStatement("INSERT INTO screening(movie_id,hall_id,start_time,end_time,price,status) VALUES(?,?,?,?,?,?)", java.sql.Statement.RETURN_GENERATED_KEYS);
                    statement.setLong(1, movieId); statement.setLong(2, slot.hallId());
                    statement.setObject(3, slot.start()); statement.setObject(4, slot.end());
                    statement.setBigDecimal(5, slot.price()); statement.setString(6, slot.status());
                    return statement;
                }, key);
                if (key.getKey() == null) throw new BusinessException(500, "场次创建失败");
                createdIds.add(key.getKey().longValue());
            } else {
                jdbc.update("UPDATE screening SET hall_id=?,start_time=?,end_time=?,price=?,status=? WHERE id=? AND movie_id=?",
                        slot.hallId(), slot.start(), slot.end(), slot.price(), slot.status(), slot.id(), movieId);
            }
        }
        validateWindow(movieId);
        return createdIds;
    }

    void validateWindow(long movieId) {
        Integer outside = jdbc.queryForObject("SELECT COUNT(*) FROM screening s JOIN movie m ON m.id=s.movie_id "
                + "WHERE m.id=? AND s.status='SCHEDULED' AND s.start_time>? "
                + "AND ((m.sale_start_time IS NOT NULL AND s.start_time<m.sale_start_time) "
                + "OR (m.sale_end_time IS NOT NULL AND s.end_time>m.sale_end_time))", Integer.class, movieId, LocalDateTime.now());
        if (outside != null && outside > 0) throw new BusinessException(400, "未来场次必须完整位于影片上架周期内，请同时调整周期或场次");
    }

    private boolean hasOrders(long id) {
        // A locking read sees orders committed while this transaction waited for the screening lock.
        return !jdbc.queryForList("SELECT id FROM ticket_order WHERE screening_id=? ORDER BY id LIMIT 1 FOR UPDATE", id).isEmpty();
    }

    private void validate(Slot slot, Map<String, Object> movie) {
        if (!slot.start().isAfter(LocalDateTime.now())) throw new BusinessException(400, "新增或修改的场次必须在未来开场");
        int duration = ((Number) movie.get("duration")).intValue();
        if (!slot.end().equals(slot.start().plusMinutes(duration + 20L))) {
            throw new BusinessException(400, "场次占用结束时间必须为开场时间加影片片长，再加 20 分钟周转时间");
        }
        Integer active = jdbc.queryForObject("SELECT COUNT(*) FROM hall h JOIN cinema c ON c.id=h.cinema_id "
                + "WHERE h.id=? AND h.status='ACTIVE' AND c.status='ACTIVE'", Integer.class, slot.hallId());
        if (active == null || active == 0) throw new BusinessException(400, "请选择营业中的影院和影厅");
        LocalDateTime start = (LocalDateTime) movie.get("sale_start_time");
        LocalDateTime end = (LocalDateTime) movie.get("sale_end_time");
        if ((start != null && slot.start().isBefore(start)) || (end != null && slot.end().isAfter(end))) {
            throw new BusinessException(400, "场次必须完整位于影片上架周期内");
        }
    }

    private Slot parse(Object input) {
        try {
            if (!(input instanceof Map<?, ?> row)) throw new IllegalArgumentException();
            Long id = row.get("id") == null ? null : Long.valueOf(row.get("id").toString());
            long hallId = Long.parseLong(row.get("hall_id").toString());
            LocalDateTime start = LocalDateTime.parse(row.get("start_time").toString());
            LocalDateTime end = LocalDateTime.parse(row.get("end_time").toString());
            BigDecimal price = new BigDecimal(row.get("price").toString()).setScale(2, java.math.RoundingMode.UNNECESSARY);
            String status = Objects.toString(row.get("status"), "SCHEDULED");
            if (hallId <= 0 || (id != null && id <= 0) || !end.isAfter(start) || price.signum() <= 0
                    || price.compareTo(new BigDecimal("99999999.99")) > 0 || !List.of("SCHEDULED", "CANCELLED").contains(status)) {
                throw new IllegalArgumentException();
            }
            return new Slot(id, hallId, start, end, price, status);
        } catch (RuntimeException exception) {
            throw new BusinessException(400, "场次的影厅、开始/结束时间、票价或状态无效；票价必须大于 0 且最多两位小数");
        }
    }

    private boolean unchanged(Slot slot, Map<String, Object> row) {
        return slot.hallId() == ((Number) row.get("hall_id")).longValue()
                && slot.start().equals(row.get("start_time")) && slot.end().equals(row.get("end_time"))
                && slot.price().compareTo((BigDecimal) row.get("price")) == 0 && slot.status().equals(row.get("status"));
    }

    private record Slot(Long id, long hallId, LocalDateTime start, LocalDateTime end, BigDecimal price, String status) {}
}
