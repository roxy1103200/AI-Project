package com.cinema.ticketing.service;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Service;

@Service
public class RuntimeDiagnostics {
    private final String buildId = buildId();
    private final Instant startedAt = Instant.now();
    private final Map<String, Evidence> requests = new ConcurrentHashMap<>();

    public Map<String, Object> runtime() {
        return Map.of("component", "java", "build_id", buildId, "started_at", startedAt.toString(),
                "reference_date", LocalDate.now(ZoneId.of("Asia/Shanghai")).toString(), "time_zone", "Asia/Shanghai",
                "contracts", Map.of("order", OrderStatusSummary.CONTRACT, "time", "cinema-time-v1"));
    }

    public void record(String requestId, String path, Map<String, Object> parameters, int status) {
        if (requestId == null || !requestId.matches("[a-fA-F0-9-]{32,36}")) return;
        Instant now = Instant.now();
        requests.entrySet().removeIf(entry -> entry.getValue().at().isBefore(now.minusSeconds(1200)));
        if (requests.size() >= 2000 && !requests.containsKey(requestId)) return;
        Evidence evidence = requests.computeIfAbsent(requestId, ignored -> new Evidence(now, new ArrayList<>()));
        synchronized (evidence.calls()) {
            if (evidence.calls().size() < 20) evidence.calls().add(Map.of("path", path, "parameters", parameters, "status", status));
        }
    }

    public Map<String, Object> evidence(String requestId) {
        Evidence evidence = requests.get(requestId);
        List<Map<String, Object>> calls = List.of();
        if (evidence != null && evidence.at().isAfter(Instant.now().minusSeconds(1200))) {
            synchronized (evidence.calls()) { calls = List.copyOf(evidence.calls()); }
        }
        return Map.of("request_id", requestId, "runtime", runtime(), "calls", calls);
    }

    private String buildId() {
        try {
            var digest = MessageDigest.getInstance("SHA-256");
            var resources = new PathMatchingResourcePatternResolver().getResources("classpath*:com/cinema/ticketing/**/*.class");
            var sorted = new ArrayList<org.springframework.core.io.Resource>(List.of(resources));
            sorted.sort(Comparator.comparing(resource -> resourceKey(resource)));
            for (var resource : sorted) {
                digest.update(resourceKey(resource).getBytes(StandardCharsets.UTF_8)); digest.update((byte) 0);
                try (var stream = resource.getInputStream()) { digest.update(stream.readAllBytes()); }
            }
            if (sorted.isEmpty()) throw new IllegalStateException("没有找到 Java 构建内容，无法生成运行版本");
            return HexFormat.of().formatHex(digest.digest());
        } catch (IOException | java.security.NoSuchAlgorithmException exception) {
            throw new IllegalStateException("无法生成 Java 运行版本", exception);
        }
    }

    private String resourceKey(org.springframework.core.io.Resource resource) {
        try {
            String value = resource.getURL().toString().replace('\\', '/');
            return value.substring(value.indexOf("com/cinema/ticketing/"));
        } catch (IOException exception) { throw new IllegalStateException("无法读取 Java 构建内容", exception); }
    }
    private record Evidence(Instant at, List<Map<String, Object>> calls) {}
}
