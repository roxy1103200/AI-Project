package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** All writes run inside CatalogService's transaction; the assessment is advisory only. */
final class MovieLifecycle {
    private final JdbcTemplate jdbc;
    private final ScreeningMutationPolicy policy;

    MovieLifecycle(JdbcTemplate jdbc, ScreeningMutationPolicy policy) {
        this.jdbc = jdbc;
        this.policy = policy;
    }

    Map<String, Object> assessment(long movieId) {
        var movies = jdbc.queryForList("SELECT id,status FROM movie WHERE id=? FOR UPDATE", movieId);
        if (movies.isEmpty()) throw new BusinessException(404, "影片不存在");
        var screenings = jdbc.queryForList("SELECT id,hall_id,end_time,status FROM screening WHERE movie_id=? ORDER BY id FOR UPDATE", movieId);
        long orders = 0;
        long locks = 0;
        long unfinished = 0;
        LocalDateTime now = LocalDateTime.now(ZoneId.of("Asia/Shanghai"));
        for (var screening : screenings) {
            long id = ((Number) screening.get("id")).longValue();
            orders += jdbc.queryForList("SELECT id FROM ticket_order WHERE screening_id=? FOR UPDATE", id).size();
            locks += policy.activeLocks(id, ((Number) screening.get("hall_id")).longValue());
            if ("SCHEDULED".equals(screening.get("status"))
                    && ((LocalDateTime) screening.get("end_time")).isAfter(now)) unfinished++;
        }
        // Lock the review roots as well, so replies/reports cannot be removed by a cascade unnoticed.
        long reviews = jdbc.queryForList("SELECT id FROM movie_review WHERE movie_id=? FOR UPDATE", movieId).size();
        List<String> reasons = new ArrayList<>();
        if (orders > 0) reasons.add("存在 " + orders + " 笔订单历史（含取消、超时和退款），请下线或归档并保留记录");
        if (reviews > 0) reasons.add("存在 " + reviews + " 条影评及其关联记录，不能物理删除");
        if (locks > 0) reasons.add("有 " + locks + " 个座位正在锁定，请等待释放后重试");
        return Map.of("can_delete", reasons.isEmpty(), "reasons", reasons,
                "screening_count", screenings.size(), "order_count", orders, "review_count", reviews,
                "active_lock_count", locks, "unfinished_screening_count", unfinished,
                "can_archive", unfinished == 0 && locks == 0, "status", movies.getFirst().get("status"));
    }

    void delete(long movieId) {
        var assessment = assessment(movieId);
        if (!Boolean.TRUE.equals(assessment.get("can_delete")))
            throw new BusinessException(409, String.join("；", reasons(assessment)));
        // Only uncommitted schedules are removed. Existing orders and reviews are never cascaded.
        jdbc.update("DELETE FROM screening WHERE movie_id=?", movieId);
        if (jdbc.update("DELETE FROM movie WHERE id=?", movieId) != 1) throw new BusinessException(404, "影片不存在");
    }

    void transition(long movieId, String action) {
        if (!List.of("offline", "archive", "restore").contains(action)) throw new BusinessException(400, "未知影片操作");
        var rows = jdbc.queryForList("SELECT id,status FROM movie WHERE id=? FOR UPDATE", movieId);
        if (rows.isEmpty()) throw new BusinessException(404, "影片不存在");
        boolean archived = "ARCHIVED".equals(rows.getFirst().get("status"));
        if ("archive".equals(action)) {
            var assessment = assessment(movieId);
            if (!Boolean.TRUE.equals(assessment.get("can_archive")))
                throw new BusinessException(409, "仍有未结束的开放场次或有效座位锁，不能归档；请先结束运营或处理无订单场次");
            jdbc.update("UPDATE movie SET status='ARCHIVED' WHERE id=?", movieId);
        } else {
            if ("offline".equals(action) && archived) throw new BusinessException(409, "影片已归档，请先恢复到已下线状态");
            if ("restore".equals(action) && !archived) throw new BusinessException(409, "只有已归档影片可以恢复");
            jdbc.update("UPDATE movie SET status='OFFLINE' WHERE id=?", movieId);
        }
    }

    @SuppressWarnings("unchecked")
    private List<String> reasons(Map<String, Object> assessment) {
        return (List<String>) assessment.get("reasons");
    }
}
