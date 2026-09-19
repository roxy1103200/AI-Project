package com.cinema.ticketing.catalog;

import com.cinema.ticketing.common.BusinessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.List;
import java.util.Map;

@Service
public class CatalogService {

    private final JdbcTemplate jdbcTemplate;

    public CatalogService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Map<String, Object>> list(String resource) {
        ResourceDefinition definition = definition(resource);
        return jdbcTemplate.queryForList(definition.listSql());
    }

    public Map<String, Object> find(String resource, long id) {
        ResourceDefinition definition = definition(resource);
        return jdbcTemplate.queryForMap(definition.findSql(), id);
    }

    public long create(String resource, Map<String, Object> values) {
        ResourceDefinition definition = definition(resource);
        rejectUserMutation(resource);
        Object[] parameters = definition.parameters(values);
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
        return key.longValue();
    }

    public void update(String resource, long id, Map<String, Object> values) {
        ResourceDefinition definition = definition(resource);
        rejectUserMutation(resource);
        Object[] parameters = definition.parameters(values, id);
        jdbcTemplate.update(definition.updateSql(), parameters);
    }

    public void delete(String resource, long id) {
        ResourceDefinition definition = definition(resource);
        jdbcTemplate.update(definition.deleteSql(), id);
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
            case "cinemas" -> ResourceDefinition.cinemas();
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
            return of("movie", "title,description,duration,release_date,director,actors,genre,status");
        }

        private static ResourceDefinition cinemas() {
            return of("cinema", "name,address,phone,status");
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
