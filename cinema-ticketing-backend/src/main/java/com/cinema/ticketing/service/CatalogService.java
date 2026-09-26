package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.SellableScreenings;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class CatalogService {

    private final JdbcTemplate jdbcTemplate;
    private final MovieScheduleEditor scheduleEditor;

    public CatalogService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
        this.scheduleEditor = new MovieScheduleEditor(jdbcTemplate);
    }

    @Cacheable(cacheNames = "catalogList", key = "#resource", condition = "#resource != 'screenings' && #resource != 'movies'")
    public List<Map<String, Object>> list(String resource) {
        if ("screenings".equals(resource)) {
            // DATETIME stores application-local time. Do not use the database's UTC NOW().
            return jdbcTemplate.queryForList("SELECT s.id, s.movie_id, s.hall_id, s.start_time, "
                    + "s.end_time, s.price, s.status FROM screening s "
                    + "JOIN movie m ON m.id = s.movie_id JOIN hall h ON h.id = s.hall_id "
                    + "JOIN cinema c ON c.id = h.cinema_id WHERE " + SellableScreenings.WHERE
                    + " ORDER BY s.start_time, s.id", LocalDateTime.now(), LocalDateTime.now(), LocalDateTime.now());
        }
        ResourceDefinition definition = definition(resource);
        return jdbcTemplate.queryForList(definition.listSql());
    }

    @Cacheable(cacheNames = "catalogDetail", key = "#resource + ':' + #id", condition = "#resource != 'movies'")
    public Map<String, Object> find(String resource, long id) {
        ResourceDefinition definition = definition(resource);
        try {
            return jdbcTemplate.queryForMap(definition.findSql(), id);
        } catch (EmptyResultDataAccessException exception) {
            throw new BusinessException(404, "资源不存在");
        }
    }

    @CacheEvict(cacheNames = {"catalogList", "catalogDetail"}, allEntries = true)
    @Transactional
    public long create(String resource, Map<String, Object> values) {
        ResourceDefinition definition = definition(resource);
        rejectUserMutation(resource);
        Object[] parameters = definition.parameters(validatedValues(resource, values));
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement statement = connection.prepareStatement(
                    definition.insertSql(), Statement.RETURN_GENERATED_KEYS);
            for (int index = 0; index < parameters.length; index++) {
                statement.setObject(index + 1, parameters[index]);
            }
            return statement;
        }, keyHolder);
        Number key = keyHolder.getKey();
        if (key == null) {
            throw new BusinessException(500, "创建数据失败");
        }
        if ("movies".equals(resource) && values.containsKey("screenings")) {
            scheduleEditor.save(key.longValue(), values.get("screenings"));
        }
        return key.longValue();
    }

    @CacheEvict(cacheNames = {"catalogList", "catalogDetail"}, allEntries = true)
    @Transactional
    public void update(String resource, long id, Map<String, Object> values) {
        ResourceDefinition definition = definition(resource);
        rejectUserMutation(resource);
        Object[] parameters = definition.parameters(validatedValues(resource, values), id);
        if (jdbcTemplate.update(definition.updateSql(), parameters) == 0) {
            throw new BusinessException(404, "资源不存在");
        }
        if ("movies".equals(resource)) {
            if (values.containsKey("screenings")) scheduleEditor.save(id, values.get("screenings"));
            else scheduleEditor.validateWindow(id);
        }
    }

    public List<Map<String, Object>> movieScreenings(long movieId) {
        return jdbcTemplate.queryForList("SELECT s.id, s.hall_id, s.start_time, s.end_time, s.price, s.status, "
                + "EXISTS(SELECT 1 FROM ticket_order o WHERE o.screening_id = s.id) has_orders "
                + "FROM screening s WHERE s.movie_id = ? ORDER BY s.start_time, s.id", movieId);
    }

    /** Future published schedules include films whose booking window has not opened. */
    public List<Map<String, Object>> publicSchedule(LocalDate from, LocalDate to) {
        long days = java.time.temporal.ChronoUnit.DAYS.between(from, to);
        if (days < 1 || days > 31) throw new BusinessException(400, "排期查询周期须为 1～31 天");
        LocalDateTime now = LocalDateTime.now();
        return jdbcTemplate.queryForList("SELECT s.id,s.movie_id,s.hall_id,s.start_time,s.end_time,s.price,s.status, "
                + "m.title movie_title,m.duration,m.sale_start_time,m.sale_end_time, "
                + "h.name hall_name,c.id cinema_id,c.name cinema_name, "
                + "CASE WHEN (m.sale_start_time IS NULL OR m.sale_start_time<=?) "
                + "AND (m.sale_end_time IS NULL OR m.sale_end_time>?) THEN 1 ELSE 0 END can_book "
                + "FROM screening s JOIN movie m ON m.id=s.movie_id JOIN hall h ON h.id=s.hall_id "
                + "JOIN cinema c ON c.id=h.cinema_id WHERE " + SellableScreenings.SCHEDULED_WHERE
                + " AND s.start_time>=? AND s.start_time<? ORDER BY s.start_time,s.id",
                now, now, now, from.atStartOfDay(), to.atStartOfDay());
    }

    public List<Map<String, Object>> hallSchedule(LocalDate from, LocalDate to) {
        long days = java.time.temporal.ChronoUnit.DAYS.between(from, to);
        if (days < 1 || days > 31) throw new BusinessException(400, "排期查询周期须为 1～31 天，截止日期不包含在周期内");
        List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                "SELECT s.id,s.movie_id,s.hall_id,m.title,m.duration,s.start_time,s.end_time,s.price,s.status "
                        + "FROM screening s JOIN movie m ON m.id=s.movie_id WHERE s.status='SCHEDULED' "
                        + "AND s.start_time < ? AND GREATEST(s.end_time, DATE_ADD(s.start_time, INTERVAL (m.duration+20) MINUTE)) > ? "
                        + "ORDER BY s.hall_id,s.start_time,s.id", to.atStartOfDay(), from.atStartOfDay());
        for (Map<String, Object> row : rows) {
            LocalDateTime filmEnd = ((LocalDateTime) row.get("start_time")).plusMinutes(((Number) row.get("duration")).longValue());
            LocalDateTime storedEnd = (LocalDateTime) row.get("end_time");
            row.put("film_end_time", filmEnd);
            row.put("occupied_end_time", storedEnd.isAfter(filmEnd.plusMinutes(20)) ? storedEnd : filmEnd.plusMinutes(20));
        }
        return rows;
    }

    @CacheEvict(cacheNames = {"catalogList", "catalogDetail"}, allEntries = true)
    public void delete(String resource, long id) {
        ResourceDefinition definition = definition(resource);
        try {
            if (jdbcTemplate.update(definition.deleteSql(), id) == 0) {
                throw new BusinessException(404, "资源不存在");
            }
        } catch (DataIntegrityViolationException exception) {
            String message = "movies".equals(resource)
                    ? "影片已关联放映场次，请先处理排片后再删除，或将影片下线"
                    : "资源仍有关联数据，无法删除";
            throw new BusinessException(409, message);
        }
    }

    private Map<String, Object> validatedValues(String resource, Map<String, Object> values) {
        if (!"movies".equals(resource)) {
            return values;
        }
        Map<String, Object> normalized = new HashMap<>(values);
        Object title = values.get("title");
        if (!(title instanceof String text) || text.isBlank() || text.trim().length() > 128) {
            throw new BusinessException(400, "影片名称不能为空，且不能超过 128 个字符");
        }
        normalized.put("title", ((String) title).trim());
        normalized.put("duration", movieDuration(values.get("duration")));
        LocalDateTime saleStart = movieDateTime(values.get("sale_start_time"));
        LocalDateTime saleEnd = movieDateTime(values.get("sale_end_time"));
        if ((saleStart == null) != (saleEnd == null) || (saleStart != null && !saleEnd.isAfter(saleStart))) {
            throw new BusinessException(400, "上架开始和截止时间必须同时填写，截止时间必须晚于开始时间");
        }
        normalized.put("sale_start_time", saleStart);
        normalized.put("sale_end_time", saleEnd);
        if (!(values.get("status") instanceof String status)
                || !List.of("UPCOMING", "ON_SHELF", "ON_SHOW", "OFFLINE").contains(status)) {
            throw new BusinessException(400, "影片上映状态无效");
        }
        validateMovieText(values, "director", 128);
        validateMovieText(values, "actors", 512);
        validateMovieText(values, "genre", 128);
        validateMovieText(values, "description", Integer.MAX_VALUE);
        Object releaseDate = values.get("release_date");
        if (releaseDate != null) {
            try {
                if (!(releaseDate instanceof String)) {
                    throw new DateTimeParseException("Not a date string", "", 0);
                }
                LocalDate.parse((String) releaseDate);
            } catch (DateTimeParseException exception) {
                throw new BusinessException(400, "上映日期必须是有效的 YYYY-MM-DD 日期");
            }
        }
        return normalized;
    }

    private int movieDuration(Object value) {
        try {
            if (value instanceof Number number) {
                int duration = new BigDecimal(number.toString()).intValueExact();
                if (duration > 0) return duration;
            }
        } catch (ArithmeticException | NumberFormatException exception) {
            throw new BusinessException(400, "片长必须是大于 0 的整数分钟数");
        }
        throw new BusinessException(400, "片长必须是大于 0 的整数分钟数");
    }

    private LocalDateTime movieDateTime(Object value) {
        if (value == null || "".equals(value)) return null;
        try {
            return LocalDateTime.parse(value.toString());
        } catch (DateTimeParseException exception) {
            throw new BusinessException(400, "上架时间必须是有效的本地日期和时间");
        }
    }

    private void validateMovieText(Map<String, Object> values, String field, int maxLength) {
        Object value = values.get(field);
        if (value != null && (!(value instanceof String text) || text.length() > maxLength)) {
            throw new BusinessException(400, "影片字段 " + field + " 的内容或长度无效");
        }
    }

    private void rejectUserMutation(String resource) {
        if ("users".equals(resource)) {
            throw new BusinessException(400, "用户必须通过 /api/auth/register 创建或通过专用账户接口修改");
        }
    }

    private ResourceDefinition definition(String resource) {
        return switch (resource) {
            case "users" -> ResourceDefinition.users();
            case "movies" -> ResourceDefinition.movies();
            case "halls" -> ResourceDefinition.halls();
            case "seats" -> ResourceDefinition.seats();
            case "screenings" -> ResourceDefinition.screenings();
            default -> throw new BusinessException(400, "不支持的资源类型: " + resource);
        };
    }

    private record ResourceDefinition(
            String table,
            List<String> fields,
            String columns,
            String readColumns) {

        private String listSql() {
            return "SELECT id, " + readColumns + " FROM " + table + " ORDER BY id DESC";
        }

        private String findSql() {
            return "SELECT id, " + readColumns + " FROM " + table + " WHERE id = ?";
        }

        private String insertSql() {
            String names = String.join(", ", fields);
            String placeholders = fields.stream().map(field -> "?").reduce((a, b) -> a + ", " + b).orElse("");
            return "INSERT INTO " + table + " (" + names + ") VALUES (" + placeholders + ")";
        }

        private String updateSql() {
            String assignments = fields.stream().map(field -> field + " = ?").reduce((a, b) -> a + ", " + b).orElse("");
            return "UPDATE " + table + " SET " + assignments + " WHERE id = ?";
        }

        private String deleteSql() {
            return "DELETE FROM " + table + " WHERE id = ?";
        }

        private Object[] parameters(Map<String, Object> values) {
            return fields.stream().map(values::get).toArray();
        }

        private Object[] parameters(Map<String, Object> values, long id) {
            Object[] parameters = parameters(values);
            Object[] result = new Object[parameters.length + 1];
            System.arraycopy(parameters, 0, result, 0, parameters.length);
            result[parameters.length] = id;
            return result;
        }

        private static ResourceDefinition users() {
            return of("users", "username,password_hash,phone,role,status",
                    "username,phone,role,status");
        }

        private static ResourceDefinition movies() {
            return of("movie", "title,description,duration,release_date,sale_start_time,sale_end_time,director,actors,genre,status",
                    "title,description,duration,release_date,sale_start_time,sale_end_time,director,actors,genre,status, "
                            + "CASE WHEN status = 'OFFLINE' THEN 'OFFLINE' "
                            + "WHEN sale_start_time IS NOT NULL AND sale_start_time > DATE_ADD(UTC_TIMESTAMP(), INTERVAL 8 HOUR) THEN 'NOT_STARTED' "
                            + "WHEN sale_end_time IS NOT NULL AND sale_end_time <= DATE_ADD(UTC_TIMESTAMP(), INTERVAL 8 HOUR) THEN 'ENDED' "
                            + "WHEN EXISTS(SELECT 1 FROM screening s JOIN hall h ON h.id=s.hall_id JOIN cinema c ON c.id=h.cinema_id "
                            + "WHERE s.movie_id=movie.id AND s.status='SCHEDULED' AND s.start_time > DATE_ADD(UTC_TIMESTAMP(), INTERVAL 8 HOUR) "
                            + "AND h.status='ACTIVE' AND c.status='ACTIVE' AND movie.status IN ('UPCOMING','ON_SHELF','ON_SHOW') "
                            + "AND (movie.sale_start_time IS NULL OR s.start_time>=movie.sale_start_time) "
                            + "AND (movie.sale_end_time IS NULL OR s.end_time<=movie.sale_end_time)) THEN 'AVAILABLE' "
                            + "ELSE 'NO_SCREENINGS' END sales_status, "
                            + "(SELECT COUNT(*) FROM screening s JOIN hall h ON h.id=s.hall_id JOIN cinema c ON c.id=h.cinema_id "
                            + "WHERE s.movie_id=movie.id AND s.status='SCHEDULED' AND s.start_time>DATE_ADD(UTC_TIMESTAMP(), INTERVAL 8 HOUR) "
                            + "AND h.status='ACTIVE' AND c.status='ACTIVE' AND movie.status IN ('UPCOMING','ON_SHELF','ON_SHOW') "
                            + "AND (movie.sale_start_time IS NULL OR s.start_time>=movie.sale_start_time) "
                            + "AND (movie.sale_end_time IS NULL OR s.end_time<=movie.sale_end_time)) future_screening_count, "
                            + "(SELECT ROUND(AVG(r.rating),1) FROM movie_review r WHERE r.movie_id=movie.id) rating_average, "
                            + "(SELECT COUNT(*) FROM movie_review r WHERE r.movie_id=movie.id) rating_count");
        }

        private static ResourceDefinition halls() {
            return of("hall", "cinema_id,name,row_count,column_count,hall_type,status");
        }

        private static ResourceDefinition seats() {
            return of("seat", "hall_id,row_no,column_no,seat_code,seat_type,status");
        }

        private static ResourceDefinition screenings() {
            return of("screening", "movie_id,hall_id,start_time,end_time,price,status");
        }

        private static ResourceDefinition of(String table, String fieldList) {
            List<String> fields = List.of(fieldList.split(","));
            return new ResourceDefinition(table, fields, fieldList, fieldList);
        }

        private static ResourceDefinition of(String table, String fieldList, String readColumns) {
            List<String> fields = List.of(fieldList.split(","));
            return new ResourceDefinition(table, fields, fieldList, readColumns);
        }
    }
}
