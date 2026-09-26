package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.CatalogService;
import com.cinema.ticketing.service.MoviePosterService;
import jakarta.validation.constraints.Positive;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.format.annotation.DateTimeFormat;
import java.time.LocalDate;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class CatalogController {

    private final CatalogService catalogService;
    private final AuthService authService;
    private final MoviePosterService moviePosterService;

    public CatalogController(CatalogService catalogService, AuthService authService,
                             MoviePosterService moviePosterService) {
        this.catalogService = catalogService;
        this.authService = authService;
        this.moviePosterService = moviePosterService;
    }

    @GetMapping("/{resource}")
    public ApiResponse<List<Map<String, Object>>> list(@PathVariable String resource,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        if ("users".equals(resource)) authService.requireAdmin(token);
        return ApiResponse.success(catalogService.list(resource));
    }

    @GetMapping("/{resource}/{id}")
    public ApiResponse<Map<String, Object>> find(
            @PathVariable String resource,
            @PathVariable @Positive long id,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        if ("users".equals(resource)) authService.requireAdmin(token);
        return ApiResponse.success(catalogService.find(resource, id));
    }

    @GetMapping("/movies/{id}/screenings")
    public ApiResponse<List<Map<String, Object>>> movieScreenings(@PathVariable @Positive long id,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        authService.requireAdmin(token);
        return ApiResponse.success(catalogService.movieScreenings(id));
    }

    @GetMapping("/halls/schedule")
    public ApiResponse<List<Map<String, Object>>> hallSchedule(
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        authService.requireAdmin(token);
        return ApiResponse.success(catalogService.hallSchedule(from, to));
    }

    @GetMapping("/screenings/schedule")
    public ApiResponse<List<Map<String, Object>>> publicSchedule(
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to) {
        return ApiResponse.success(catalogService.publicSchedule(from, to));
    }

    @PostMapping(value = "/{resource}", consumes = "application/json")
    public ApiResponse<Map<String, Long>> create(
            @PathVariable String resource,
            @RequestHeader(value = "X-Auth-Token", required = false) String token,
            @RequestBody Map<String, Object> values) {
        authService.requireAdmin(token);
        long id = catalogService.create(resource, values);
        return ApiResponse.success(Map.of("id", id));
    }

    @PutMapping(value = "/{resource}/{id}", consumes = "application/json")
    public ApiResponse<Void> update(
            @PathVariable String resource,
            @PathVariable @Positive long id,
            @RequestHeader(value = "X-Auth-Token", required = false) String token,
            @RequestBody Map<String, Object> values) {
        authService.requireAdmin(token);
        catalogService.update(resource, id, values);
        return ApiResponse.success(null);
    }

    @DeleteMapping("/{resource}/{id}")
    public ApiResponse<Void> delete(
            @PathVariable String resource,
            @PathVariable @Positive long id,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        authService.requireAdmin(token);
        catalogService.delete(resource, id);
        if ("movies".equals(resource)) {
            moviePosterService.removeAfterMovieDeleted(id);
        }
        return ApiResponse.success(null);
    }
}
