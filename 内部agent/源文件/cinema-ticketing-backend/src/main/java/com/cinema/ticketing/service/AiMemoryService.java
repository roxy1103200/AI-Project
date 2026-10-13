package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;

import jakarta.validation.constraints.*;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.*;

/** 记忆归属与有效版本由 SQL 校验，索引任务和记忆更新在同一事务提交。 */
@Service
public class AiMemoryService {
    private final JdbcTemplate jdbc;
    private static final Set<String> CATEGORIES =
            Set.of("GENERAL", "GENRE", "CINEMA", "SEAT", "HABIT");

    public AiMemoryService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record Input(
            @NotBlank @Size(max = 500) String content,
            @NotBlank @Pattern(regexp = "GENERAL|GENRE|CINEMA|SEAT|HABIT") String category,
            UUID sourceMessageId,
            @Min(1) Integer version) {}

    public record Candidate(@NotNull UUID id, @Min(1) int version) {}

    public record VerifyInput(
            @Positive long userId,
            @NotNull @Size(max = 20) List<@jakarta.validation.Valid Candidate> candidates) {}

    public record JobAck(@NotNull UUID leaseToken, boolean success) {}

    public List<Map<String, Object>> list(long userId) {
        return jdbc.queryForList(
                "SELECT id,category,content,source_kind,source_message_id,version,updated_at FROM"
                    + " ai_user_memory WHERE user_id=? AND channel='AGENT' AND status='ACTIVE'"
                    + " ORDER BY updated_at DESC,id LIMIT 200",
                userId);
    }

    @Transactional
    public Map<String, Object> create(long userId, Input input) {
        validate(input);
        // 固定上限并锁定用户，防止同时创建绕过数量限制。
        jdbc.queryForObject("SELECT id FROM users WHERE id=? FOR UPDATE", Long.class, userId);
        if (jdbc.queryForObject(
                        "SELECT COUNT(*) FROM ai_user_memory WHERE user_id=? AND status='ACTIVE'",
                        Long.class,
                        userId)
                >= 200) throw new BusinessException(400, "最多保存 200 条记忆，请先整理旧记忆");
        String id = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();
        jdbc.update(
                "INSERT INTO"
                    + " ai_user_memory(id,user_id,channel,category,content,source_kind,source_message_id,version,status,created_at,updated_at)"
                    + " VALUES(?,?,'AGENT',?,?,?, ?,1,'ACTIVE',?,?)",
                id,
                userId,
                input.category(),
                input.content().trim(),
                input.sourceMessageId() == null ? "EXPLICIT" : "CONFIRMED",
                input.sourceMessageId() == null ? null : input.sourceMessageId().toString(),
                now,
                now);
        enqueue(id, 1, now);
        return Map.of("id", id, "version", 1);
    }

    @Transactional
    public Map<String, Object> update(long userId, String id, Input input) {
        validate(input);
        if (input.version() == null) throw new BusinessException(400, "缺少当前记忆版本，请刷新后修改");
        int changed =
                jdbc.update(
                        "UPDATE ai_user_memory SET"
                            + " content=?,category=?,version=version+1,updated_at=? WHERE id=? AND"
                            + " user_id=? AND channel='AGENT' AND status='ACTIVE' AND version=?",
                        input.content().trim(),
                        input.category(),
                        LocalDateTime.now(),
                        id,
                        userId,
                        input.version());
        if (changed == 0) stale(userId, id);
        enqueue(id, input.version() + 1, LocalDateTime.now());
        return Map.of("id", id, "version", input.version() + 1);
    }

    @Transactional
    public void delete(long userId, String id, int version) {
        LocalDateTime now = LocalDateTime.now();
        int changed =
                jdbc.update(
                        "UPDATE ai_user_memory SET"
                            + " status='DELETED',version=version+1,deleted_at=?,updated_at=? WHERE"
                            + " id=? AND user_id=? AND channel='AGENT' AND status='ACTIVE' AND"
                            + " version=?",
                        now,
                        now,
                        id,
                        userId,
                        version);
        if (changed == 0) stale(userId, id);
        enqueue(id, version + 1, now);
    }

    public List<Map<String, Object>> verify(VerifyInput input) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (Candidate item : input.candidates())
            result.addAll(
                    jdbc.queryForList(
                            "SELECT id,category,content,version FROM ai_user_memory WHERE id=? AND"
                                + " user_id=? AND channel='AGENT' AND status='ACTIVE' AND"
                                + " version=?",
                            item.id().toString(),
                            input.userId(),
                            item.version()));
        return result;
    }

    /** 同一记忆的事件按序领取；过期租约可重新领取，迟到的确认不能覆盖新租约。 */
    @Transactional
    public List<Map<String, Object>> claim() {
        LocalDateTime now = LocalDateTime.now();
        var events =
                jdbc.queryForList(
                        "SELECT o.id,o.memory_id,o.version FROM ai_memory_index_outbox o WHERE"
                            + " ((o.state='PENDING' AND o.available_at<=?) OR (o.state='RUNNING'"
                            + " AND o.lease_until<=?)) AND NOT EXISTS(SELECT 1 FROM"
                            + " ai_memory_index_outbox p WHERE p.memory_id=o.memory_id AND"
                            + " p.id<o.id AND p.state<>'DONE') ORDER BY o.id LIMIT 10 FOR UPDATE"
                            + " SKIP LOCKED",
                        now,
                        now);
        List<Map<String, Object>> result = new ArrayList<>();
        for (var event : events) {
            String lease = UUID.randomUUID().toString();
            jdbc.update(
                    "UPDATE ai_memory_index_outbox SET"
                        + " state='RUNNING',attempts=attempts+1,lease_token=?,lease_until=? WHERE"
                        + " id=?",
                    lease,
                    now.plusMinutes(5),
                    event.get("id"));
            var rows =
                    jdbc.queryForList(
                            "SELECT id,user_id,channel,category,content,version,status FROM"
                                + " ai_user_memory WHERE id=?",
                            event.get("memory_id"));
            Map<String, Object> job = new HashMap<>();
            job.put("jobId", event.get("id"));
            job.put("memoryId", event.get("memory_id"));
            job.put("eventVersion", event.get("version"));
            job.put("leaseToken", lease);
            job.put("memory", rows.isEmpty() ? null : rows.getFirst());
            result.add(job);
        }
        return result;
    }

    public void ack(long id, JobAck ack) {
        int changed =
                jdbc.update(
                        "UPDATE ai_memory_index_outbox SET"
                            + " state=?,available_at=?,lease_token=NULL,lease_until=NULL WHERE id=?"
                            + " AND state='RUNNING' AND lease_token=? AND lease_until>?",
                        ack.success() ? "DONE" : "PENDING",
                        LocalDateTime.now().plusSeconds(30),
                        id,
                        ack.leaseToken().toString(),
                        LocalDateTime.now());
        if (changed == 0) throw new BusinessException(409, "索引任务租约已更新");
    }

    /** 通过新事件重新投影所有记忆（含删除标记），不会改动用户记忆。 */
    @Transactional
    public int rebuild() {
        return jdbc.update(
                "UPDATE ai_memory_index_outbox SET state='PENDING',available_at=? WHERE"
                    + " state='DONE' AND id IN (SELECT latest_id FROM (SELECT MAX(id) latest_id"
                    + " FROM ai_memory_index_outbox GROUP BY memory_id) latest)",
                LocalDateTime.now());
    }

    private void enqueue(String id, int version, LocalDateTime now) {
        jdbc.update(
                "INSERT INTO"
                    + " ai_memory_index_outbox(memory_id,version,state,available_at,created_at)"
                    + " VALUES(?,?,'PENDING',?,?)",
                id,
                version,
                now,
                now);
    }

    private void stale(long userId, String id) {
        Long count =
                jdbc.queryForObject(
                        "SELECT COUNT(*) FROM ai_user_memory WHERE id=? AND user_id=? AND"
                            + " status='ACTIVE'",
                        Long.class,
                        id,
                        userId);
        throw new BusinessException(count == 0 ? 404 : 409, count == 0 ? "记忆不存在" : "记忆已被修改，请刷新后重试");
    }

    private void validate(Input input) {
        if (input.content() == null
                || input.content().isBlank()
                || input.content().length() > 500
                || !CATEGORIES.contains(input.category()))
            throw new BusinessException(400, "记忆内容或分类无效");
    }
}
