package com.cinema.ticketing.common;

import java.util.HashMap;
import java.util.Map;
import java.util.regex.Pattern;

/** Render deadline wording from the same numeric parameter used by order validation. */
public final class RefundPolicyText {
    private static final Pattern DEADLINE = Pattern.compile(
            "((?:开场|开映|放映|影片开始|电影开始)前|提前|距(?:离)?(?:开场|开映|放映))\\s*"
                    + "(?:[0-9零〇一二三四五六七八九十百千万两点.]+\\s*(?:分钟|小时)|半小时)");

    private RefundPolicyText() {}

    public static String render(Number cutoffMinutes, String description) {
        String minutes = String.valueOf(cutoffMinutes.longValue());
        return "退票截止时间为开场前 " + minutes + " 分钟，到达截止时间及之后不能退票。\n"
                + normalizeDescription(cutoffMinutes, description);
    }

    public static String normalizeDescription(Number cutoffMinutes, String description) {
        String minutes = String.valueOf(cutoffMinutes.longValue());
        String details = (description == null ? "" : description.trim()).replaceAll(
                "退票截止时间为开场前\\s*\\d+\\s*分钟，到达截止时间及之后不能退票。\\s*", "");
        return DEADLINE.matcher(details).replaceAll("$1 " + minutes + " 分钟");
    }

    public static Map<String, Object> normalize(Map<String, Object> row, String contentKey) {
        Map<String, Object> result = new HashMap<>(row);
        result.put(contentKey, render((Number) row.get("cutoff_minutes"), String.valueOf(row.get(contentKey))));
        return result;
    }
}
