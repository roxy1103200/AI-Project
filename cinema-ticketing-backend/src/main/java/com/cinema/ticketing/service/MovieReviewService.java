package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.JdbcTimes;
import com.cinema.ticketing.common.ReviewEligibility;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
public class MovieReviewService {
    private static final String REPLY_COLUMNS = "p.id,p.user_id,p.content,p.status,p.revision,p.moderation_note,"
            + "p.created_at,p.updated_at,u.username,(u.role='ADMIN') official";
    private static final Set<String> REPORT_REASONS = Set.of("ABUSE", "SPAM", "SPOILER", "ILLEGAL", "OTHER");
    private final JdbcTemplate jdbc;

    public MovieReviewService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Map<String, Object> list(long movieId, int page, Long userId) {
        requireMovie(movieId);
        Map<String, Object> result = new HashMap<>(jdbc.queryForMap(
                "SELECT COUNT(*) reviewCount,ROUND(AVG(r.rating),1) averageRating FROM movie_review r WHERE r.movie_id=? AND "
                        + ReviewEligibility.WHERE, movieId));
        result.put("reviews", JdbcTimes.asLocalDateTimes(jdbc.queryForList(
                "SELECT r.id,r.user_id,r.rating,r.content,r.created_at,r.updated_at,u.username,"
                        + "(SELECT COUNT(*) FROM movie_review_like l WHERE l.review_id=r.id) likeCount,"
                        + "EXISTS(SELECT 1 FROM movie_review_like l WHERE l.review_id=r.id AND l.user_id=?) liked,"
                        + "(SELECT COUNT(*) FROM movie_review_reply p WHERE p.review_id=r.id AND p.status='APPROVED') replyCount "
                        + "FROM movie_review r JOIN users u ON u.id=r.user_id WHERE r.movie_id=? AND " + ReviewEligibility.WHERE
                        + " ORDER BY r.updated_at DESC,r.id DESC LIMIT 10 OFFSET ?", userId, movieId, (page - 1) * 10)));
        result.put("page", page);
        boolean qualified = userId != null && !qualifiedOrders(movieId, userId, false).isEmpty();
        result.put("canReview", qualified);
        result.put("eligibilityReason", userId == null ? "登录并购票，场次结束或验票后可以评价"
                : qualified ? "已验证购票与观影资格" : "需要该影片的有效已出票电影票，并满足场次结束或已验票；取消、退票不计入资格");
        if (userId != null) {
            var own = JdbcTimes.asLocalDateTimes(jdbc.queryForList(
                    "SELECT r.id,r.rating,r.content,r.status,r.revision,r.moderation_note,r.created_at,r.updated_at,("
                            + ReviewEligibility.WHERE + ") publiclyVisible FROM movie_review r WHERE r.movie_id=? AND r.user_id=?",
                    movieId, userId));
            result.put("ownReview", own.isEmpty() ? null : own.getFirst());
            if (!own.isEmpty() && "HIDDEN".equals(own.getFirst().get("status"))) {
                result.put("canReview", false);
                result.put("eligibilityReason", "您的影评已被隐藏，请联系影院处理或删除原评价");
            }
            result.put("ownReplies", JdbcTimes.asLocalDateTimes(jdbc.queryForList("SELECT p.id,p.review_id,p.content,p.status,"
                    + "p.moderation_note,p.updated_at,(" + ReviewEligibility.WHERE + ") parent_visible "
                    + "FROM movie_review_reply p JOIN movie_review r ON r.id=p.review_id WHERE r.movie_id=? AND p.user_id=? "
                    + "ORDER BY p.updated_at DESC,p.id DESC LIMIT 20", movieId, userId)));
        }
        return result;
    }

    @Transactional
    public void save(long movieId, long userId, int rating, String content) {
        requireMovie(movieId);
        if (qualifiedOrders(movieId, userId, true).isEmpty())
            throw new BusinessException(403, "有效购票且场次结束或已验票后才能评价；管理员也适用该规则");
        var own = jdbc.queryForList("SELECT status FROM movie_review WHERE movie_id=? AND user_id=? FOR UPDATE", movieId, userId);
        if (!own.isEmpty() && "HIDDEN".equals(own.getFirst().get("status")))
            throw new BusinessException(403, "这条影评已被管理员隐藏，请联系影院处理或删除原评价");
        LocalDateTime now = LocalDateTime.now();
        jdbc.update("INSERT INTO movie_review(movie_id,user_id,rating,content,status,created_at,updated_at) "
                        + "VALUES(?,?,?,?,'PENDING',?,?) ON DUPLICATE KEY UPDATE rating=?,content=?,status='PENDING',"
                        + "revision=revision+1,moderation_note='',moderated_by=NULL,moderated_at=NULL,updated_at=?",
                movieId, userId, rating, content.trim(), now, now, rating, content.trim(), now);
    }

    @Transactional
    public void delete(long movieId, long userId) {
        var rows = jdbc.queryForList("SELECT id FROM movie_review WHERE movie_id=? AND user_id=? FOR UPDATE", movieId, userId);
        if (!rows.isEmpty()) jdbc.update("DELETE FROM movie_review WHERE id=?", rows.getFirst().get("id"));
    }

    @Transactional
    public void like(long movieId, long reviewId, long userId, boolean liked) {
        Map<String, Object> review = requirePublicReview(movieId, reviewId, true);
        if (((Number) review.get("user_id")).longValue() == userId) throw new BusinessException(400, "不能给自己的影评点赞");
        if (liked) jdbc.update("INSERT IGNORE INTO movie_review_like(review_id,user_id,created_at) VALUES(?,?,?)", reviewId, userId, LocalDateTime.now());
        else jdbc.update("DELETE FROM movie_review_like WHERE review_id=? AND user_id=?", reviewId, userId);
    }

    public Map<String, Object> replies(long movieId, long reviewId, int page, Long userId) {
        requirePublicReview(movieId, reviewId, false);
        String visible = "p.status='APPROVED' OR p.user_id=?";
        long total = jdbc.queryForObject("SELECT COUNT(*) FROM movie_review_reply p WHERE p.review_id=? AND (" + visible + ")",
                Long.class, reviewId, userId);
        var items = JdbcTimes.asLocalDateTimes(jdbc.queryForList("SELECT " + REPLY_COLUMNS
                        + " FROM movie_review_reply p JOIN users u ON u.id=p.user_id WHERE p.review_id=? AND (" + visible + ") "
                        + "ORDER BY p.created_at,p.id LIMIT 10 OFFSET ?", reviewId, userId, (page - 1) * 10));
        for (var item : items) if (userId == null || ((Number) item.get("user_id")).longValue() != userId) item.remove("moderation_note");
        return Map.of("items", items, "total", total, "page", page);
    }

    @Transactional
    public void reply(long movieId, long reviewId, long userId, String content) {
        requirePublicReview(movieId, reviewId, true);
        long total = jdbc.queryForObject("SELECT COUNT(*) FROM movie_review_reply WHERE review_id=? AND user_id=?", Long.class, reviewId, userId);
        if (total >= 20) throw new BusinessException(429, "同一影评最多保留 20 条回复，请先整理已有回复");
        LocalDateTime now = LocalDateTime.now();
        jdbc.update("INSERT INTO movie_review_reply(review_id,user_id,content,status,created_at,updated_at) VALUES(?,?,?,'PENDING',?,?)",
                reviewId, userId, content.trim(), now, now);
    }

    @Transactional
    public void deleteReply(long movieId, long reviewId, long replyId, long userId) {
        requireReview(movieId, reviewId, true);
        jdbc.update("DELETE FROM movie_review_reply WHERE id=? AND review_id=? AND user_id=?", replyId, reviewId, userId);
    }

    @Transactional
    public void report(long movieId, long reviewId, Long replyId, long userId, String reason, String content) {
        if (!REPORT_REASONS.contains(reason)) throw new BusinessException(400, "未知的举报原因");
        if ("OTHER".equals(reason) && content.isBlank()) throw new BusinessException(400, "选择其他问题时请补充举报说明");
        Map<String, Object> target = requirePublicReview(movieId, reviewId, true);
        if (replyId != null) {
            var replies = jdbc.queryForList("SELECT * FROM movie_review_reply WHERE id=? AND review_id=? AND status='APPROVED' FOR UPDATE", replyId, reviewId);
            if (replies.isEmpty()) throw new BusinessException(404, "回复不存在或未公开");
            target = replies.getFirst();
        }
        if (((Number) target.get("user_id")).longValue() == userId) throw new BusinessException(400, "不能举报自己的内容");
        String key = (replyId == null ? "REVIEW:" + reviewId : "REPLY:" + replyId) + ":" + target.get("revision");
        jdbc.update("INSERT IGNORE INTO movie_review_report(review_id,reply_id,target_key,target_revision,user_id,reason,content,"
                        + "reported_content,created_at) VALUES(?,?,?,?,?,?,?,?,?)", reviewId, replyId, key, target.get("revision"),
                userId, reason, content.trim(), target.get("content"), LocalDateTime.now());
    }

    private List<Long> qualifiedOrders(long movieId, long userId, boolean lock) {
        return jdbc.queryForList("SELECT ro.id FROM ticket_order ro JOIN screening rs ON rs.id=ro.screening_id "
                        + "JOIN movie rm ON rm.id=rs.movie_id WHERE rs.movie_id=? AND ro.user_id=? "
                        + "AND EXISTS(SELECT 1 FROM order_item ri WHERE ri.order_id=ro.id AND " + ReviewEligibility.TICKET
                        + ") ORDER BY ro.id LIMIT 1" + (lock ? " FOR UPDATE" : ""), Long.class, movieId, userId);
    }

    private Map<String, Object> requirePublicReview(long movieId, long reviewId, boolean lock) {
        Map<String, Object> review = requireReview(movieId, reviewId, lock);
        if (!Boolean.TRUE.equals(review.get("publiclyVisible")) && !"1".equals(String.valueOf(review.get("publiclyVisible"))))
            throw new BusinessException(404, "影评不存在或未公开");
        return review;
    }

    private Map<String, Object> requireReview(long movieId, long reviewId, boolean lock) {
        var rows = jdbc.queryForList("SELECT r.*,(" + ReviewEligibility.WHERE + ") publiclyVisible FROM movie_review r WHERE r.id=? AND r.movie_id=?"
                + (lock ? " FOR UPDATE" : ""), reviewId, movieId);
        if (rows.isEmpty()) throw new BusinessException(404, "影评不存在");
        return rows.getFirst();
    }

    private void requireMovie(long movieId) {
        if (jdbc.queryForList("SELECT id FROM movie WHERE id=?", movieId).isEmpty()) throw new BusinessException(404, "影片不存在");
    }
}
