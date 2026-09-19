package com.cinema.ticketing.catalog;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.auth.AuthService;
import jakarta.validation.constraints.Positive;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class CatalogController {

    private final CatalogService catalogService;
    private final AuthService authService;

    public CatalogController(CatalogService catalogService, AuthService authService) {
        this.catalogService = catalogService;
        this.authService = authService;
    }

    @GetMapping("/{resource}")
    public ApiResponse<List<Map<String, Object>>> list(@PathVariable String resource) {
        return ApiResponse.success(catalogService.list(resource));
    }

    @GetMapping("/{resource}/{id}")
    public ApiResponse<Map<String, Object>> find(
            @PathVariable String resource,
            @PathVariable @Positive long id) {
        return ApiResponse.success(catalogService.find(resource, id));
    }

    @PostMapping("/{resource}")
    public ApiResponse<Map<String, Long>> create(
            @PathVariable String resource,
            @RequestHeader("X-Auth-Token") String token,
            @RequestBody Map<String, Object> values) {
        authService.requireAdmin(token);
        long id = catalogService.create(resource, values);
        return ApiResponse.success(Map.of("id", id));
    }

    @PutMapping("/{resource}/{id}")
    public ApiResponse<Void> update(
            @PathVariable String resource,
            @PathVariable @Positive long id,
            @RequestHeader("X-Auth-Token") String token,
            @RequestBody Map<String, Object> values) {
        authService.requireAdmin(token);
        catalogService.update(resource, id, values);
        return ApiResponse.success(null);
    }

    @DeleteMapping("/{resource}/{id}")
    public ApiResponse<Void> delete(
            @PathVariable String resource,
            @PathVariable @Positive long id,
            @RequestHeader("X-Auth-Token") String token) {
        authService.requireAdmin(token);
        catalogService.delete(resource, id);
        return ApiResponse.success(null);
    }
}
