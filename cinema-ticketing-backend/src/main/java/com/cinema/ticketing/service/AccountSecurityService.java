package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;

/** Explicit account administration: never exposes password hashes or accepts arbitrary fields. */
@Service
public class AccountSecurityService {
    private final JdbcTemplate jdbc;
    private final AuthService auth;

    public AccountSecurityService(JdbcTemplate jdbc, AuthService auth) {
        this.jdbc = jdbc;
        this.auth = auth;
    }

    public List<Map<String, Object>> list(String token) {
        auth.requireAdmin(token);
        return jdbc.queryForList(
                "SELECT id,username,role,status,session_version FROM users ORDER BY id LIMIT 500");
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public void updateAccess(String token, long id, String role, String status, long version) {
        auth.requireAdmin(token);
        if (!("USER".equals(role) || "ADMIN".equals(role))
                || !("ACTIVE".equals(status) || "DISABLED".equals(status))) {
            throw new BusinessException(400, "角色或账户状态无效");
        }
        // Serialize admin removals to preserve at least one available administrator.
        List<Long> admins =
                jdbc.queryForList(
                        "SELECT id FROM users WHERE role='ADMIN' AND status='ACTIVE' ORDER BY id"
                            + " FOR UPDATE",
                        Long.class);
        auth.requireAdmin(token);
        var rows =
                jdbc.queryForList(
                        "SELECT role,status,session_version FROM users WHERE id=? FOR UPDATE", id);
        if (rows.isEmpty()) throw new BusinessException(404, "账户不存在");
        var account = rows.get(0);
        if (((Number) account.get("session_version")).longValue() != version) throw conflict();
        if (role.equals(account.get("role")) && status.equals(account.get("status"))) return;
        if (admins.contains(id)
                && admins.size() == 1
                && !("ADMIN".equals(role) && "ACTIVE".equals(status))) {
            throw new BusinessException(409, "必须保留至少一个可用管理员");
        }
        jdbc.update(
                "UPDATE users SET role=?,status=?,session_version=session_version+1 WHERE id=?",
                role,
                status,
                id);
    }

    @Transactional
    public void revoke(String token, long id, long version) {
        auth.requireAdmin(token);
        if (jdbc.update(
                        "UPDATE users SET session_version=session_version+1 WHERE id=? AND"
                            + " session_version=?",
                        id,
                        version)
                != 1) throw conflict();
    }

    private BusinessException conflict() {
        return new BusinessException(409, "账户已被更新，请刷新后重试");
    }
}
