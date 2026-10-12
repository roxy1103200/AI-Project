package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.Objects;

/** Call mutable checks while holding the screening write lock, before changing a schedule. */
final class ScreeningMutationPolicy {
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;

    ScreeningMutationPolicy(JdbcTemplate jdbc, StringRedisTemplate redis) {
        this.jdbc = jdbc;
        this.redis = redis;
    }

    boolean hasOrders(long screeningId) {
        // Current read includes orders committed while waiting for the screening lock.
        return !jdbc.queryForList("SELECT id FROM ticket_order WHERE screening_id=? ORDER BY id LIMIT 1 FOR UPDATE",
                screeningId).isEmpty();
    }

    long activeLocks(long screeningId, long hallId) {
        List<String> keys = jdbc.queryForList("SELECT id FROM seat WHERE hall_id=? ORDER BY id", Long.class, hallId)
                .stream().map(id -> "seat:lock:" + screeningId + ":" + id).toList();
        if (keys.isEmpty()) return 0;
        try {
            // Bounded batches avoid scanning unrelated Redis keys or a large multi-get.
            long count = 0;
            for (int offset = 0; offset < keys.size(); offset += 200) {
                var values = redis.opsForValue().multiGet(keys.subList(offset, Math.min(offset + 200, keys.size())));
                if (values == null) throw new IllegalStateException("Missing Redis result");
                count += values.stream().filter(Objects::nonNull).count();
            }
            return count;
        } catch (RuntimeException exception) {
            throw new BusinessException(503, "暂时无法核验座位锁，请稍后重试；本次未修改排期");
        }
    }

    void requireMutable(long screeningId, long hallId) {
        if (hasOrders(screeningId)) throw new BusinessException(409, "场次存在订单历史，不能修改或删除；请保留历史记录");
        if (activeLocks(screeningId, hallId) > 0) throw new BusinessException(409, "场次有观众正在锁座，请等待座位锁释放后重试");
        // A provisional snapshot alone is not a sale. Recapture against the next actual layout.
        jdbc.update("DELETE FROM screening_capacity_snapshot WHERE screening_id=?", screeningId);
    }
}
