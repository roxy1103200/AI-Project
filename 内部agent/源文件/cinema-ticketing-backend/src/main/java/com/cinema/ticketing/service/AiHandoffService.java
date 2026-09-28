package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/** Short lived credentials for the read only assistant, bound to the current login. */
@Service
public class AiHandoffService {
    private static final Duration TTL = Duration.ofMinutes(10);
    private final StringRedisTemplate redis;
    private final AuthService auth;

    public AiHandoffService(StringRedisTemplate redis, AuthService auth) {
        this.redis = redis;
        this.auth = auth;
    }

    public Map<String, Object> issue(String authToken, String sessionId) {
        auth.requireUserId(authToken);
        String credential = UUID.randomUUID().toString() + UUID.randomUUID();
        redis.opsForValue().set(key(credential), authToken + "\n" + sessionId, TTL);
        return Map.of("credential", credential, "expiresAt", Instant.now().plus(TTL).toString());
    }

    public Map<String, Object> resolve(String credential) {
        if (credential == null || !credential.matches("[a-f0-9-]{72}")) {
            throw new BusinessException(401, "转接凭证无效，请重新转接");
        }
        String stored = redis.opsForValue().get(key(credential));
        if (stored == null) {
            throw new BusinessException(401, "转接已过期，请重新转接");
        }
        String[] fields = stored.split("\n", 2);
        long userId = auth.requireUserId(fields[0]);
        return Map.of("userId", userId, "sessionId", fields[1], "scope", "cinema:read");
    }

    private String key(String credential) {
        return "ai:handoff:" + credential;
    }
}
