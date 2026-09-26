package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.dto.CinemaSaveRequest;
import com.cinema.ticketing.entity.Cinema;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.CinemaService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/cinemas")
public class CinemaController {

    private final CinemaService cinemaService;
    private final AuthService authService;

    public CinemaController(CinemaService cinemaService, AuthService authService) {
        this.cinemaService = cinemaService;
        this.authService = authService;
    }

    @GetMapping
    public ApiResponse<List<Cinema>> list() {
        return ApiResponse.success(cinemaService.list());
    }

    @GetMapping("/{id}")
    public ApiResponse<Cinema> find(@PathVariable long id) {
        return ApiResponse.success(cinemaService.find(id));
    }

    @PostMapping
    public ApiResponse<Map<String, Long>> create(
            @RequestHeader(value = "X-Auth-Token", required = false) String token,
            @Valid @RequestBody CinemaSaveRequest request) {
        authService.requireAdmin(token);
        return ApiResponse.success(Map.of("id", cinemaService.create(request)));
    }

    @PutMapping("/{id}")
    public ApiResponse<Void> update(
            @PathVariable long id,
            @RequestHeader(value = "X-Auth-Token", required = false) String token,
            @Valid @RequestBody CinemaSaveRequest request) {
        authService.requireAdmin(token);
        cinemaService.update(id, request);
        return ApiResponse.success(null);
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(
            @PathVariable long id,
            @RequestHeader(value = "X-Auth-Token", required = false) String token) {
        authService.requireAdmin(token);
        cinemaService.delete(id);
        return ApiResponse.success(null);
    }
}
