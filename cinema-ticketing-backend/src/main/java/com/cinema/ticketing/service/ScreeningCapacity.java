package com.cinema.ticketing.service;

import org.springframework.jdbc.core.JdbcTemplate;
import java.time.LocalDateTime;
import java.time.ZoneId;

/** Called with the hall write lock held, before the first seat lock or order is committed. */
final class ScreeningCapacity {
    private ScreeningCapacity() {}

    static void capture(JdbcTemplate jdbc, long screeningId, long hallId) {
        if (!jdbc.queryForList("SELECT screening_id FROM screening_capacity_snapshot WHERE screening_id=? FOR UPDATE", screeningId).isEmpty()) return;
        // Legacy orders cannot prove what the sellable layout was; keep their historical capacity unknown.
        if (!jdbc.queryForList("SELECT id FROM ticket_order WHERE screening_id=? LIMIT 1 FOR UPDATE", screeningId).isEmpty()) return;
        // A current read avoids an older repeatable-read view established by the idempotency lookup.
        int count = jdbc.queryForList("SELECT id FROM seat WHERE hall_id=? AND status='AVAILABLE' ORDER BY id FOR UPDATE",
                Long.class, hallId).size();
        if (count == 0) return;
        jdbc.update("INSERT INTO screening_capacity_snapshot(screening_id,sellable_seat_count,captured_at) VALUES(?,?,?)",
                screeningId, count, LocalDateTime.now(ZoneId.of("Asia/Shanghai")));
    }
}
