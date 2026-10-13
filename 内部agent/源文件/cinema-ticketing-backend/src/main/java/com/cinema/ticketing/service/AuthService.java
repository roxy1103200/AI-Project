package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.dto.CurrentSession;
import com.cinema.ticketing.dto.LoginResult;
import com.cinema.ticketing.entity.UserAccount;
import com.cinema.ticketing.mapper.UserMapper;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class AuthService {
    private static final Duration TOKEN_TTL = Duration.ofHours(2);
    private final UserMapper userMapper;
    private final StringRedisTemplate redisTemplate;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();
    private final Map<String, LoginSession> sessions = new ConcurrentHashMap<>();

    public AuthService(UserMapper userMapper) {
        this(userMapper, null);
    }

    @Autowired
    public AuthService(UserMapper userMapper, StringRedisTemplate redisTemplate) {
        this.userMapper = userMapper;
        this.redisTemplate = redisTemplate;
    }

    public UserAccount register(String username, String password, String phone) {
        if (username == null || username.isBlank()) {
            throw new BusinessException(400, "用户名不能为空");
        }
        validatePassword(password);
        if (userMapper.findByUsername(username) != null) {
            throw new BusinessException(409, "用户名已存在");
        }
        UserAccount account = new UserAccount();
        account.setUsername(username);
        account.setPasswordHash(passwordEncoder.encode(password));
        account.setPhone(phone);
        account.setRole("USER");
        account.setStatus("ACTIVE");
        userMapper.insert(account);
        return account;
    }

    public LoginResult login(String username, String password) {
        UserAccount account = userMapper.findByUsername(username);
        if (account == null
                || password == null
                || passwordBytes(password) > 72
                || !passwordEncoder.matches(password, account.getPasswordHash())) {
            throw new BusinessException(401, "用户名或密码错误");
        }
        if (!usable(account)) {
            throw new BusinessException(403, "账户不可用");
        }
        String token = UUID.randomUUID().toString();
        LoginSession session =
                new LoginSession(
                        account.getId(),
                        account.getRole(),
                        account.getSessionVersion(),
                        Instant.now().plus(TOKEN_TTL));
        if (redisTemplate == null) {
            sessions.put(token, session);
        } else {
            redisTemplate
                    .opsForHash()
                    .putAll(
                            sessionKey(token),
                            Map.of(
                                    "userId", String.valueOf(session.userId()),
                                    "role", session.role(),
                                    "sessionVersion", String.valueOf(session.version())));
            redisTemplate.expire(sessionKey(token), TOKEN_TTL);
        }
        return new LoginResult(
                token,
                account.getId(),
                account.getUsername(),
                account.getRole(),
                TOKEN_TTL.toSeconds());
    }

    /** All protected requests check durable account state; verification never renews the token. */
    public CurrentSession current(String token) {
        LoginSession session = requireSession(token);
        UserAccount account = verifiedAccount(token, session);
        Long ttl =
                redisTemplate == null
                        ? Duration.between(Instant.now(), session.expiresAt()).toSeconds()
                        : redisTemplate.getExpire(sessionKey(token));
        if (ttl == null || ttl <= 0) throw expired();
        return new CurrentSession(account.getId(), account.getUsername(), account.getRole(), ttl);
    }

    public void logout(String token) {
        if (token == null) return;
        if (redisTemplate == null) sessions.remove(token);
        else redisTemplate.delete(sessionKey(token));
    }

    @Transactional
    public void logoutAll(String token) {
        UserAccount account = requireAccount(token);
        // SQL is authoritative. Old Redis entries may expire naturally without granting access.
        if (userMapper.revokeSessions(account.getId(), account.getSessionVersion()) != 1) {
            throw expired();
        }
    }

    @Transactional
    public void changePassword(String token, String currentPassword, String newPassword) {
        UserAccount account = requireAccount(token);
        validatePassword(newPassword);
        UserAccount secret = userMapper.findByIdWithPassword(account.getId());
        if (secret == null
                || currentPassword == null
                || passwordBytes(currentPassword) > 72
                || !passwordEncoder.matches(currentPassword, secret.getPasswordHash())) {
            throw new BusinessException(400, "当前密码不正确");
        }
        if (passwordEncoder.matches(newPassword, secret.getPasswordHash())) {
            throw new BusinessException(400, "新密码不能与当前密码相同");
        }
        // Hash and version change atomically, preventing a concurrent credential change being lost.
        if (userMapper.changePassword(
                        account.getId(),
                        passwordEncoder.encode(newPassword),
                        account.getSessionVersion())
                != 1) throw expired();
    }

    public void requireAdmin(String token) {
        if (!"ADMIN".equals(requireAccount(token).getRole())) {
            throw new BusinessException(403, "需要管理员权限");
        }
    }

    public long requireUserId(String token) {
        return requireAccount(token).getId();
    }

    public boolean isAdmin(String token) {
        return "ADMIN".equals(requireAccount(token).getRole());
    }

    private UserAccount requireAccount(String token) {
        return verifiedAccount(token, requireSession(token));
    }

    private UserAccount verifiedAccount(String token, LoginSession session) {
        UserAccount account = userMapper.findById(session.userId());
        if (!usable(account)
                || account.getSessionVersion() != session.version()
                || !account.getRole().equals(session.role())) {
            logout(token);
            throw expired();
        }
        return account;
    }

    private boolean usable(UserAccount account) {
        return account != null
                && "ACTIVE".equals(account.getStatus())
                && ("ADMIN".equals(account.getRole()) || "USER".equals(account.getRole()));
    }

    private LoginSession requireSession(String token) {
        if (token == null || !token.matches("[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")) {
            throw expired();
        }
        if (redisTemplate == null) {
            LoginSession session = sessions.get(token);
            if (session == null || !session.expiresAt().isAfter(Instant.now())) {
                sessions.remove(token);
                throw expired();
            }
            return session;
        }
        Map<Object, Object> values = redisTemplate.opsForHash().entries(sessionKey(token));
        Long ttl = redisTemplate.getExpire(sessionKey(token));
        if (values.isEmpty() || ttl == null || ttl <= 0 || !values.containsKey("sessionVersion")) {
            throw expired();
        }
        try {
            return new LoginSession(
                    Long.parseLong(String.valueOf(values.get("userId"))),
                    String.valueOf(values.get("role")),
                    Long.parseLong(String.valueOf(values.get("sessionVersion"))),
                    null);
        } catch (NumberFormatException exception) {
            throw expired();
        }
    }

    private String sessionKey(String token) {
        return "auth:session:" + token;
    }

    private int passwordBytes(String password) {
        return password.getBytes(StandardCharsets.UTF_8).length;
    }

    private void validatePassword(String password) {
        if (password == null || password.length() < 8 || passwordBytes(password) > 72) {
            throw new BusinessException(400, "密码至少 8 位，UTF-8 编码不超过 72 字节");
        }
    }

    private BusinessException expired() {
        return new BusinessException(401, "账户或登录已失效，请重新登录");
    }

    private record LoginSession(Long userId, String role, long version, Instant expiresAt) {}
}
