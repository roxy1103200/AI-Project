package com.cinema.ticketing.common;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 把 JDBC 读出来的时间值统一成 {@link LocalDateTime}。
 *
 * <p>为什么需要它：同一个 ResultSet 里两类时间列的返回类型不同 —— DATETIME 列
 * （expire_at / paid_at / start_time）经 Connector/J 的 getObject() 得到 LocalDateTime，
 * 而 TIMESTAMP 列（created_at 等）得到 java.sql.Timestamp。两者序列化成 JSON 后长得不一样：
 * 前者是不带时区的字面量 {@code 2026-09-22T20:57:02}，后者带偏移
 * {@code 2026-09-22T12:57:02.000+00:00}。同一份响应里混着两种表示法，前端按一套规则
 * 解析必然踩坑，所以对外一律转成 LocalDateTime。
 *
 * <p>时区语义：TIMESTAMP 存的是瞬间，{@code Timestamp.toLocalDateTime()} 给出的是 JVM
 * 默认时区下的墙钟时间；DATETIME 没有时区，逐字读出。本项目的 JVM 跑在 UTC+8，业务时间
 * 也一律由 {@code LocalDateTime.now()} 生成，两者因此落到同一套「本地墙钟」表示法上。
 *
 * <p>注意这不影响 {@code serverTimezone} 的取值 —— 那个声明必须是数据库服务器的真实时区，
 * 写错了 TIMESTAMP 列读出来的瞬间就会偏，转换方法本身纠不回来。
 */
public final class JdbcTimes {

    private JdbcTimes() {
    }

    /** 单个时间列。null 之外的类型一律抛异常，不静默返回 null —— 静默会掩盖真实的类型变化。 */
    public static LocalDateTime asLocalDateTime(Object value) {
        if (value instanceof LocalDateTime localDateTime) {
            return localDateTime;
        }
        if (value instanceof Timestamp timestamp) {
            return timestamp.toLocalDateTime();
        }
        throw new IllegalStateException(
                "无法解析时间列，实际类型: " + (value == null ? "null" : value.getClass().getName()));
    }

    /** 把一行结果里所有 java.sql.Timestamp 就地换成 LocalDateTime，其余值（含 null）原样保留。 */
    public static Map<String, Object> asLocalDateTimes(Map<String, Object> row) {
        row.replaceAll((key, value) -> value instanceof Timestamp timestamp
                ? timestamp.toLocalDateTime()
                : value);
        return row;
    }

    /** 多行版本。 */
    public static List<Map<String, Object>> asLocalDateTimes(List<Map<String, Object>> rows) {
        rows.forEach(JdbcTimes::asLocalDateTimes);
        return rows;
    }
}
