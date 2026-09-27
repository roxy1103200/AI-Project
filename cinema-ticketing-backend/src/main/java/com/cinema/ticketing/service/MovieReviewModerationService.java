package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.JdbcTimes;
import com.cinema.ticketing.common.ReviewEligibility;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
public class MovieReviewModerationService {
    private static final Set<String> STATUSES = Set.of("PENDING", "APPROVED", "REJECTED", "HIDDEN");
    private static final String CONTENT_LIST = "SELECT 'REVIEW' kind,r.id,r.id review_id,r.movie_id,r.user_id,u.username,m.title movie_title,"
            + "r.rating,r.content,r.status,r.revision,r.moderation_note,r.created_at,r.updated_at,(" + ReviewEligibility.WHERE + ") publicly_visible,"
            + "(SELECT COUNT(*) FROM movie_review_report q WHERE q.review_id=r.id AND q.reply_id IS NULL AND q.status='OPEN') open_reports "
            + "FROM movie_review r JOIN users u ON u.id=r.user_id JOIN movie m ON m.id=r.movie_id "
            + "UNION ALL SELECT 'REPLY',p.id,p.review_id,r.movie_id,p.user_id,u.username,m.title,NULL,p.content,p.status,p.revision,"
            + "p.moderation_note,p.created_at,p.updated_at,(p.status='APPROVED' AND " + ReviewEligibility.WHERE + "),"
            + "(SELECT COUNT(*) FROM movie_review_report q WHERE q.reply_id=p.id AND q.status='OPEN') "
            + "FROM movie_review_reply p JOIN movie_review r ON r.id=p.review_id JOIN users u ON u.id=p.user_id JOIN movie m ON m.id=r.movie_id";
    private final JdbcTemplate jdbc;

    public MovieReviewModerationService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Map<String, Object> list(String kind, String status, String query, int page) {
        List<Object> parameters = new ArrayList<>();
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        if (kind != null && !kind.isBlank()) { table(kind); where.append(" AND v.kind=?"); parameters.add(kind); }
        if (status != null && !status.isBlank()) { validateStatus(status); where.append(" AND v.status=?"); parameters.add(status); }
        if (query != null && !query.isBlank()) {
            where.append(" AND (v.movie_title LIKE ? OR v.username LIKE ? OR v.content LIKE ?)");
            String keyword = "%" + query.trim() + "%";
            parameters.addAll(List.of(keyword, keyword, keyword));
        }
        String from = " FROM (" + CONTENT_LIST + ") v" + where;
        Map<String, Object> summary = jdbc.queryForMap("SELECT COUNT(*) total,COALESCE(SUM(v.status='PENDING'),0) pending,"
                + "COALESCE(SUM(v.status='HIDDEN'),0) hidden,COALESCE(SUM(v.open_reports),0) openReports" + from, parameters.toArray());
        parameters.add((page - 1) * 20);
        var items = JdbcTimes.asLocalDateTimes(jdbc.queryForList("SELECT v.*" + from + " ORDER BY v.updated_at DESC,v.kind,v.id DESC LIMIT 20 OFFSET ?", parameters.toArray()));
        return Map.of("items", items, "summary", summary, "page", page);
    }

    @Transactional
    public void moderate(String kind, long id, long revision, String status, String note, long adminId) {
        validateStatus(status);
        Map<String, Object> target = lockTarget(kind, id);
        apply(kind, target, revision, status, note, adminId);
    }

    public List<Map<String, Object>> history(String kind, long id) {
        table(kind);
        return JdbcTimes.asLocalDateTimes(jdbc.queryForList("SELECT a.*,u.username admin_name FROM movie_review_moderation a "
                + "LEFT JOIN users u ON u.id=a.admin_id WHERE a.target_kind=? AND a.target_id=? ORDER BY a.id DESC LIMIT 50", kind, id));
    }

    public Map<String, Object> reports(String status, int page) {
        if (status != null && !status.isBlank() && !Set.of("OPEN", "RESOLVED", "DISMISSED").contains(status))
            throw new BusinessException(400, "未知的举报处理状态");
        String where = status == null || status.isBlank() ? "" : " WHERE q.status=?";
        List<Object> parameters = new ArrayList<>();
        if (!where.isEmpty()) parameters.add(status);
        long total = jdbc.queryForObject("SELECT COUNT(*) FROM movie_review_report q" + where, Long.class, parameters.toArray());
        parameters.add((page - 1) * 20);
        var items = JdbcTimes.asLocalDateTimes(jdbc.queryForList("SELECT q.*,u.username reporter_name,m.title movie_title,"
                + "IF(q.reply_id IS NULL,'REVIEW','REPLY') target_kind,COALESCE(q.reply_id,q.review_id) target_id,"
                + "IF(q.reply_id IS NULL,r.content,p.content) current_content,IF(q.reply_id IS NULL,r.revision,p.revision) current_revision,"
                + "IF(q.reply_id IS NULL,r.status,p.status) current_status "
                + "FROM movie_review_report q JOIN movie_review r ON r.id=q.review_id JOIN movie m ON m.id=r.movie_id "
                + "JOIN users u ON u.id=q.user_id LEFT JOIN movie_review_reply p ON p.id=q.reply_id" + where
                + " ORDER BY q.created_at DESC,q.id DESC LIMIT 20 OFFSET ?", parameters.toArray()));
        return Map.of("items", items, "total", total, "page", page);
    }

    @Transactional
    public void resolve(long reportId, String status, String note, boolean hideTarget, Long revision, long adminId) {
        if (!Set.of("RESOLVED", "DISMISSED").contains(status)) throw new BusinessException(400, "请选择处理或驳回举报");
        if (note.isBlank()) throw new BusinessException(400, "请填写举报处理说明");
        var reports = jdbc.queryForList("SELECT * FROM movie_review_report WHERE id=?", reportId);
        if (reports.isEmpty()) throw new BusinessException(404, "举报不存在");
        var report = reports.getFirst();
        String kind = report.get("reply_id") == null ? "REVIEW" : "REPLY";
        long id = ((Number) (report.get("reply_id") == null ? report.get("review_id") : report.get("reply_id"))).longValue();
        Map<String, Object> target = lockTarget(kind, id);
        var lockedReports = jdbc.queryForList("SELECT status FROM movie_review_report WHERE id=? FOR UPDATE", reportId);
        if (lockedReports.isEmpty()) throw new BusinessException(404, "举报不存在");
        if (!"OPEN".equals(lockedReports.getFirst().get("status"))) throw new BusinessException(409, "举报已处理，请刷新列表");
        if (hideTarget) {
            if (!"RESOLVED".equals(status) || revision == null) throw new BusinessException(400, "隐藏内容需要确认当前版本并按有效举报处理");
            apply(kind, target, revision, "HIDDEN", note, adminId);
        }
        jdbc.update("UPDATE movie_review_report SET status=?,resolution_note=?,resolved_by=?,resolved_at=? WHERE id=?",
                status, note.trim(), adminId, LocalDateTime.now(), reportId);
    }

    private void apply(String kind, Map<String, Object> target, long revision, String status, String note, long adminId) {
        String explanation = note == null ? "" : note.trim();
        if (((Number) target.get("revision")).longValue() != revision) throw new BusinessException(409, "内容已变化，请刷新后再审核");
        if (("HIDDEN".equals(status) || "REJECTED".equals(status)) && explanation.isBlank())
            throw new BusinessException(400, "拒绝或隐藏需填写原因（1～1000 字）；审核通过可留空");
        LocalDateTime now = LocalDateTime.now();
        jdbc.update("UPDATE " + table(kind) + " SET status=?,revision=revision+1,moderation_note=?,moderated_by=?,moderated_at=? WHERE id=?",
                status, explanation, adminId, now, target.get("id"));
        jdbc.update("INSERT INTO movie_review_moderation(target_kind,target_id,target_revision,from_status,to_status,content_snapshot,"
                        + "rating_snapshot,note,admin_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", kind, target.get("id"), revision,
                target.get("status"), status, target.get("content"), target.get("rating"), explanation, adminId, now);
    }

    private Map<String, Object> lockTarget(String kind, long id) {
        String table = table(kind);
        if ("REPLY".equals(kind)) {
            var replies = jdbc.queryForList("SELECT review_id FROM movie_review_reply WHERE id=?", id);
            if (replies.isEmpty()) throw new BusinessException(404, "回复不存在");
            jdbc.queryForList("SELECT id FROM movie_review WHERE id=? FOR UPDATE", replies.getFirst().get("review_id"));
        }
        var targets = jdbc.queryForList("SELECT * FROM " + table + " WHERE id=? FOR UPDATE", id);
        if (targets.isEmpty()) throw new BusinessException(404, "内容不存在");
        return targets.getFirst();
    }

    private String table(String kind) {
        return switch (kind) {
            case "REVIEW" -> "movie_review";
            case "REPLY" -> "movie_review_reply";
            default -> throw new BusinessException(400, "未知的内容类型");
        };
    }

    private void validateStatus(String status) {
        if (!STATUSES.contains(status)) throw new BusinessException(400, "未知的审核状态");
    }
}
