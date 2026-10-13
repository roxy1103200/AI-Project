package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.dto.LoginResult;
import com.cinema.ticketing.dto.CurrentSession;
import com.cinema.ticketing.entity.UserAccount;
import com.cinema.ticketing.mapper.UserMapper;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
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
        validateCredentials(username, password);
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
        if (account == null || !passwordEncoder.matches(password, account.getPasswordHash())) {
            throw new BusinessException(401, "用户名或密码错误");
        }
        if (!"ACTIVE".equals(account.getStatus())) {
            throw new BusinessException(403, "用户已被禁用");
        }
        String token = UUID.randomUUID().toString();
        LoginSession session = new LoginSession(account.getId(), account.getRole(), Instant.now().plus(TOKEN_TTL));
        if (redisTemplate == null) {
            sessions.put(token, session);
        } else {
            Map<String, String> values = new HashMap<>();
            values.put("userId", String.valueOf(session.userId()));
            values.put("role", session.role());
            redisTemplate.opsForHash().putAll(sessionKey(token), values);
            redisTemplate.expire(sessionKey(token), TOKEN_TTL);
        }
        return new LoginResult(token, account.getId(), account.getUsername(), account.getRole(), TOKEN_TTL.toSeconds());
    }

    /** Verify the account against the database without extending the login lifetime. */
    public CurrentSession current(String token) {
        LoginSession session = requireSession(token);
        UserAccount account = userMapper.findById(session.userId());
        if (account == null || !"ACTIVE".equals(account.getStatus())
                || !("USER".equals(account.getRole()) || "ADMIN".equals(account.getRole()))) {
            logout(token);
            throw new BusinessException(401, "账户不可用，请重新登录");
        }
        long remaining;
        if (redisTemplate == null) {
            remaining = Duration.between(Instant.now(), session.expiresAt()).toSeconds();
            sessions.replace(token, session, new LoginSession(session.userId(), account.getRole(), session.expiresAt()));
        } else {
            // Atomically refresh role only on an existing expiring token; never recreate an expired login.
            var script = new org.springframework.data.redis.core.script.DefaultRedisScript<Long>(
                    "local ttl=redis.call('TTL',KEYS[1]); if ttl<=0 then return 0 end; "
                    + "redis.call('HSET',KEYS[1],'role',ARGV[1]); return ttl", Long.class);
            Long ttl = redisTemplate.execute(script, java.util.List.of(sessionKey(token)), account.getRole());
            remaining = ttl == null ? 0 : ttl;
        }
        if (remaining <= 0) throw new BusinessException(401, "登录已失效，请重新登录");
        return new CurrentSession(account.getId(), account.getUsername(), account.getRole(), remaining);
    }

    public void logout(String token) {
        if (token != null) {
            if (redisTemplate == null) {
                sessions.remove(token);
            } else {
                redisTemplate.delete(sessionKey(token));
            }
        }
    }

    public void requireAdmin(String token) {
        LoginSession session = requireSession(token);
        if (!"ADMIN".equals(session.role())) {
            throw new BusinessException(403, "需要管理员权限");
        }
    }

    public long requireUserId(String token) {
        return requireSession(token).userId();
    }

    public boolean isAdmin(String token) {
        return "ADMIN".equals(requireSession(token).role());
    }

    private LoginSession requireSession(String token) {
        if (token == null || token.isBlank()) {
            throw new BusinessException(401, "登录已失效，请重新登录");
        }
        LoginSession session;
        if (redisTemplate == null) {
            session = sessions.get(token);
            if (session == null || session.expiresAt().isBefore(Instant.now())) {
                sessions.remove(token);
                throw new BusinessException(401, "登录已失效，请重新登录");
            }
        } else {
            Map<Object, Object> values = redisTemplate.opsForHash().entries(sessionKey(token));
            if (values.isEmpty()) {
                throw new BusinessException(401, "登录已失效，请重新登录");
            }
            session = new LoginSession(Long.parseLong(String.valueOf(values.get("userId"))),
                    String.valueOf(values.get("role")), null);
        }
        return session;
    }

    private String sessionKey(String token) {
        return "auth:session:" + token;
    }

    private void validateCredentials(String username, String password) {
        if (username == null || username.isBlank() || password == null || password.length() < 8) {
            throw new BusinessException(400, "用户名不能为空，密码长度不能少于 8 位");
        }
    }

    private record LoginSession(Long userId, String role, Instant expiresAt) {
    }
}
