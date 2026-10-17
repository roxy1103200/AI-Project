package com.cinema.ticketing.common;

import com.cinema.ticketing.service.RuntimeDiagnostics;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.ContentCachingRequestWrapper;

/** Bounded, private query evidence. Authentication material and free text are never captured. */
@Component
public class QueryEvidenceFilter extends OncePerRequestFilter {
    private static final Set<String> FIELDS = Set.of("movieScope", "queryScope", "screeningDate", "screeningDateFrom", "screeningDateTo",
            "screeningHourFrom", "screeningHourTo", "releaseDateFrom", "releaseDateTo", "releaseDatePreferred", "movieId", "cinemaId", "page", "pageSize");
    private final RuntimeDiagnostics diagnostics;
    private final ObjectMapper mapper;
    public QueryEvidenceFilter(RuntimeDiagnostics diagnostics, ObjectMapper mapper) { this.diagnostics = diagnostics; this.mapper = mapper; }

    @Override protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return !(path.startsWith("/internal/movies") || path.equals("/internal/screenings")
                || path.equals("/internal/recommendations") || path.startsWith("/internal/orders/"));
    }

    @Override protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        var wrapped = new ContentCachingRequestWrapper(request, 16384);
        try { chain.doFilter(wrapped, response); }
        finally {
            Map<String, Object> parameters = new LinkedHashMap<>();
            wrapped.getParameterMap().forEach((key, values) -> { if (FIELDS.contains(key) && values.length == 1 && values[0].length() < 80) parameters.put(key, values[0]); });
            if (wrapped.getContentAsByteArray().length > 0) {
                try {
                    var body = mapper.readTree(wrapped.getContentAsByteArray());
                    FIELDS.forEach(key -> { if (body.has(key) && body.get(key).isValueNode() && body.get(key).asText().length() < 80) parameters.put(key, body.get(key).asText()); });
                } catch (IOException ignored) { /* Malformed bodies remain the controller's validation concern. */ }
            }
            diagnostics.record(request.getHeader("X-Trace-Id"), request.getRequestURI(), parameters, response.getStatus());
        }
    }
}
