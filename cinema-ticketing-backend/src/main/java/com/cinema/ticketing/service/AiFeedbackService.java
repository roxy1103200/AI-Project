package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import jakarta.validation.constraints.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
public class AiFeedbackService {
    private final JdbcTemplate jdbc;
    private static final Set<String> SYNC_STATES = Set.of("PENDING", "SYNCED", "FAILED", "NOT_APPLICABLE", "UNAVAILABLE");

    public AiFeedbackService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public record FeedbackInput(
            @NotNull java.util.UUID messageId, @NotNull java.util.UUID sessionId,
            @NotBlank @Pattern(regexp = "DIFY|AGENT") String provider,
            @NotNull @Size(max = 64) String providerMessageId, @Positive Long userId,
            @NotBlank @Size(max = 2000) String question, @NotNull @Size(max = 1000) String normalizedQuestion,
            @NotNull @Size(max = 8000) String answer, @NotNull @Size(max = 48) String intent,
            @DecimalMin("0") @DecimalMax("1") BigDecimal confidence, @NotNull @Size(max = 48) String intentSource,
            @NotNull @Size(max = 4000) String entitiesJson, @NotNull @Size(max = 2000) String toolCallsJson,
            @NotNull @Size(max = 64) String errorCode, @Pattern(regexp = "like|dislike") String rating,
            @Pattern(regexp = "misunderstood|irrelevant|inaccurate|outdated|unresolved|error|other") String reason,
            @NotNull @Size(max = 500) String content,
            @NotBlank @Pattern(regexp = "PENDING|SYNCED|FAILED|NOT_APPLICABLE|UNAVAILABLE") String syncStatus) {}

    @Transactional
    public void save(FeedbackInput input) {
        LocalDateTime now = LocalDateTime.now();
        jdbc.update("""
                INSERT INTO ai_message_feedback(message_id,session_id,user_id,provider,provider_message_id,
                    question,normalized_question,answer,intent,confidence,intent_source,entities_json,tool_calls_json,
                    error_code,rating,reason,feedback_content,provider_sync_status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON DUPLICATE KEY UPDATE
                    status=IF((rating <=> VALUES(rating)) AND (reason <=> VALUES(reason))
                        AND (feedback_content <=> VALUES(feedback_content)),status,'OPEN'),
                    reviewed_at=IF(status='OPEN',NULL,reviewed_at),
                    reviewed_by=IF(status='OPEN',NULL,reviewed_by),
                    rating=VALUES(rating),reason=VALUES(reason),feedback_content=VALUES(feedback_content),
                    provider_sync_status=VALUES(provider_sync_status),updated_at=VALUES(updated_at)
                """, input.messageId().toString(), input.sessionId().toString(), input.userId(), input.provider(),
                input.providerMessageId(), input.question(), input.normalizedQuestion(), input.answer(), input.intent(),
                input.confidence(), input.intentSource(), input.entitiesJson(), input.toolCallsJson(), input.errorCode(),
                input.rating(), input.reason(), input.content(), input.syncStatus(), now, now);
    }

    public void sync(String messageId, String status) {
        if (!SYNC_STATES.contains(status)) throw new BusinessException(400, "无效的同步状态");
        if (jdbc.update("UPDATE ai_message_feedback SET provider_sync_status=? WHERE message_id=?", status, messageId) == 0)
            throw new BusinessException(404, "反馈不存在");
    }

    public Map<String, Object> list(String provider, String rating, String status, String reason, String query, int page, int size) {
        if (page < 1 || page > 100000 || size < 1 || size > 50) throw new BusinessException(400, "分页参数无效");
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        List<Object> parameters = new ArrayList<>();
        filter(where, parameters, "provider", provider, Set.of("DIFY", "AGENT"));
        filter(where, parameters, "rating", rating, Set.of("like", "dislike"));
        filter(where, parameters, "status", status, Set.of("OPEN", "RESOLVED"));
        filter(where, parameters, "reason", reason, Set.of("misunderstood", "irrelevant", "inaccurate", "outdated", "unresolved", "error", "other"));
        if (query != null && !query.isBlank()) {
            if (query.length() > 120) throw new BusinessException(400, "搜索内容过长");
            where.append(" AND (question LIKE ? OR normalized_question LIKE ? OR feedback_content LIKE ?)");
            for (int i = 0; i < 3; i++) parameters.add("%" + query.trim() + "%");
        }
        Map<String, Object> summary = jdbc.queryForMap("SELECT COUNT(*) total,COALESCE(SUM(rating='like'),0) likes,"
                + "COALESCE(SUM(rating='dislike'),0) dislikes,COALESCE(SUM(status='OPEN' AND rating IS NOT NULL),0) unresolved,"
                + "COALESCE(SUM(provider_sync_status IN ('PENDING','FAILED','UNAVAILABLE')),0) sync_issues"
                + " FROM ai_message_feedback" + where, parameters.toArray());
        parameters.add(size);
        parameters.add((page - 1) * size);
        var items = jdbc.queryForList("SELECT * FROM ai_message_feedback" + where + " ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?", parameters.toArray());
        return Map.of("items", items, "summary", summary, "page", page, "size", size);
    }

    private void filter(StringBuilder where, List<Object> parameters, String column, String value, Set<String> allowed) {
        if (value == null || value.isBlank()) return;
        if (!allowed.contains(value)) throw new BusinessException(400, "筛选参数无效");
        where.append(" AND ").append(column).append("=?");
        parameters.add(value);
    }

    public void review(long id, String status, String note, long adminId) {
        if (!Set.of("OPEN", "RESOLVED").contains(status)) throw new BusinessException(400, "无效的处理状态");
        if (jdbc.update("UPDATE ai_message_feedback SET status=?,review_note=?,reviewed_by=?,reviewed_at=? WHERE id=?",
                status, note.trim(), adminId, LocalDateTime.now(), id) == 0) throw new BusinessException(404, "反馈不存在");
    }
}
