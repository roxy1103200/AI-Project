package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.service.RuntimeDiagnostics;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/ai")
public class RuntimeDiagnosticsController {
    private final RuntimeDiagnostics diagnostics;
    private final String internalToken;
    public RuntimeDiagnosticsController(RuntimeDiagnostics diagnostics, @Value("${ai.internal-token}") String internalToken) {
        this.diagnostics = diagnostics; this.internalToken = internalToken;
    }
    @GetMapping("/runtime")
    public Map<String, Object> runtime(@RequestHeader("X-Internal-Token") String token) { verify(token); return diagnostics.runtime(); }

    @GetMapping("/regression/{requestId}")
    public Map<String, Object> evidence(@RequestHeader("X-Internal-Token") String token, @PathVariable String requestId) {
        verify(token); return diagnostics.evidence(requestId);
    }
    private void verify(String token) {
        if (!MessageDigest.isEqual(token.getBytes(StandardCharsets.UTF_8), internalToken.getBytes(StandardCharsets.UTF_8))) {
            throw new BusinessException(401, "无效的内部服务凭证");
        }
    }
}
