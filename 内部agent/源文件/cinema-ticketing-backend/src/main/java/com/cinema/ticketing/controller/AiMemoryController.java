package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.service.AiMemoryService;
import com.cinema.ticketing.service.AuthService;

import jakarta.validation.Valid;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

@RestController
public class AiMemoryController {
    private final AiMemoryService memory;
    private final AuthService auth;
    private final String internalToken;

    public AiMemoryController(
            AiMemoryService memory,
            AuthService auth,
            @Value("${ai.internal-token}") String internalToken) {
        this.memory = memory;
        this.auth = auth;
        this.internalToken = internalToken;
    }

    @GetMapping("/api/ai/memories")
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestHeader("X-Auth-Token") String token) {
        return ApiResponse.success(memory.list(auth.requireUserId(token)));
    }

    @PostMapping("/api/ai/memories")
    public ApiResponse<Map<String, Object>> create(
            @RequestHeader("X-Auth-Token") String token,
            @Valid @RequestBody AiMemoryService.Input input) {
        return ApiResponse.success(memory.create(auth.requireUserId(token), input));
    }

    @PatchMapping("/api/ai/memories/{id}")
    public ApiResponse<Map<String, Object>> update(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable UUID id,
            @Valid @RequestBody AiMemoryService.Input input) {
        return ApiResponse.success(memory.update(auth.requireUserId(token), id.toString(), input));
    }

    @DeleteMapping("/api/ai/memories/{id}")
    public ApiResponse<Void> delete(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable UUID id,
            @RequestParam int version) {
        if (version < 1) throw new BusinessException(400, "无效的记忆版本");
        memory.delete(auth.requireUserId(token), id.toString(), version);
        return ApiResponse.success(null);
    }

    @GetMapping("/internal/ai/memories")
    public List<Map<String, Object>> internalList(
            @RequestHeader("X-Internal-Token") String token, @RequestParam long userId) {
        verify(token);
        if (userId < 1) throw new BusinessException(400, "无效的用户标识");
        return memory.list(userId);
    }

    @PostMapping("/internal/ai/memories/verify")
    public List<Map<String, Object>> check(
            @RequestHeader("X-Internal-Token") String token,
            @Valid @RequestBody AiMemoryService.VerifyInput input) {
        verify(token);
        return memory.verify(input);
    }

    @PostMapping("/internal/ai/memory-index/claim")
    public List<Map<String, Object>> claim(@RequestHeader("X-Internal-Token") String token) {
        verify(token);
        return memory.claim();
    }

    @PostMapping("/internal/ai/memory-index/{id}/ack")
    public Map<String, Boolean> ack(
            @RequestHeader("X-Internal-Token") String token,
            @PathVariable long id,
            @Valid @RequestBody AiMemoryService.JobAck input) {
        verify(token);
        memory.ack(id, input);
        return Map.of("saved", true);
    }

    @PostMapping("/api/admin/ai-memory/reindex")
    public ApiResponse<Map<String, Integer>> rebuild(@RequestHeader("X-Auth-Token") String token) {
        auth.requireAdmin(token);
        return ApiResponse.success(Map.of("queued", memory.rebuild()));
    }

    private void verify(String token) {
        if (!MessageDigest.isEqual(
                internalToken.getBytes(StandardCharsets.UTF_8),
                token.getBytes(StandardCharsets.UTF_8)))
            throw new BusinessException(401, "无效的内部服务凭证");
    }
}
