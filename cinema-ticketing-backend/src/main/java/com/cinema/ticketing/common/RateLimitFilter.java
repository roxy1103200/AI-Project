package com.cinema.ticketing.common;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Map;

@Component
@ConditionalOnBean(RateLimitService.class)
public class RateLimitFilter extends OncePerRequestFilter {

    private final RateLimitService rateLimitService;
    private final ObjectMapper objectMapper;
    private final int requestLimit;
    private final String trustedProxyHeader;

    public RateLimitFilter(RateLimitService rateLimitService, ObjectMapper objectMapper,
                           @Value("${rate-limit.requests-per-minute:120}") int requestLimit,
                           @Value("${rate-limit.trusted-proxy-header:cinema-nginx}") String trustedProxyHeader) {
        this.rateLimitService = rateLimitService;
        this.objectMapper = objectMapper;
        this.requestLimit = requestLimit;
        this.trustedProxyHeader = trustedProxyHeader;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return !path.startsWith("/api/") || "/api/health".equals(path);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String clientKey = request.getRemoteAddr();
        if (trustedProxyHeader.equals(request.getHeader("X-Trusted-Proxy"))) {
            String realIp = request.getHeader("X-Real-IP");
            if (realIp != null && !realIp.isBlank()) {
                clientKey = realIp.trim();
            }
        }
        try {
            if (!rateLimitService.allow(clientKey, requestLimit, 60)) {
                response.setStatus(429);
                response.setContentType(MediaType.APPLICATION_JSON_VALUE);
                response.setCharacterEncoding("UTF-8");
                objectMapper.writeValue(response.getWriter(), Map.of("code", 429, "message", "请求过于频繁"));
                return;
            }
        } catch (RuntimeException exception) {
            // Redis is a protection mechanism; a Redis outage must not make the API unavailable.
        }
        filterChain.doFilter(request, response);
    }
}
