package com.cinema.ticketing.common;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;

@Service
public class RateLimitService {

    private static final DefaultRedisScript<Long> RATE_LIMIT_SCRIPT = new DefaultRedisScript<>(
            "local count = redis.call('incr', KEYS[1]) "
                    + "if count == 1 then redis.call('expire', KEYS[1], ARGV[2]) end "
                    + "if count > tonumber(ARGV[1]) then return 0 end return 1", Long.class);

    private final StringRedisTemplate redisTemplate;

    public RateLimitService(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    public boolean allow(String clientKey, int limit, int windowSeconds) {
        String window = String.valueOf(Instant.now().getEpochSecond() / windowSeconds);
        String key = "rate_limit:http:" + clientKey + ":" + window;
        Long result = redisTemplate.execute(RATE_LIMIT_SCRIPT, List.of(key),
                String.valueOf(limit), String.valueOf(windowSeconds));
        return Long.valueOf(1L).equals(result);
    }
}
