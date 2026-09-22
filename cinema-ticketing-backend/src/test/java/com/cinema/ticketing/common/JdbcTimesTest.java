package com.cinema.ticketing.common;

import org.junit.jupiter.api.Test;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

class JdbcTimesTest {

    private static final LocalDateTime WALL_CLOCK = LocalDateTime.of(2026, 9, 22, 20, 51, 59);

    @Test
    void passesLocalDateTimeThroughUnchanged() {
        assertEquals(WALL_CLOCK, JdbcTimes.asLocalDateTime(WALL_CLOCK));
    }

    @Test
    void turnsTimestampIntoLocalWallClock() {
        assertEquals(WALL_CLOCK, JdbcTimes.asLocalDateTime(Timestamp.valueOf(WALL_CLOCK)));
    }

    @Test
    void rejectsUnexpectedTypesInsteadOfSilentlyReturningNull() {
        assertThrows(IllegalStateException.class, () -> JdbcTimes.asLocalDateTime("2026-09-22 20:51:59"));
        assertThrows(IllegalStateException.class, () -> JdbcTimes.asLocalDateTime(null));
    }

    /** 一行里混着两类时间列时，TIMESTAMP 要被换掉、DATETIME 和 null 原样留着。 */
    @Test
    void normalisesTimestampColumnsInARowAndLeavesTheRestAlone() {
        Map<String, Object> row = new HashMap<>();
        row.put("created_at", Timestamp.valueOf(WALL_CLOCK));
        row.put("expire_at", WALL_CLOCK);
        row.put("paid_at", null);
        row.put("status", "UNPAID");

        JdbcTimes.asLocalDateTimes(List.of(row));

        assertEquals(WALL_CLOCK, row.get("created_at"));
        assertInstanceOf(LocalDateTime.class, row.get("created_at"));
        assertEquals(WALL_CLOCK, row.get("expire_at"));
        assertNull(row.get("paid_at"));
        assertEquals("UNPAID", row.get("status"));
    }
}
