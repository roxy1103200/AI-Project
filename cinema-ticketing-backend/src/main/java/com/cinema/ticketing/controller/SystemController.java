package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import jakarta.validation.constraints.NotBlank;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@Validated
@RestController
public class SystemController {

    @GetMapping("/api/health")
    public ApiResponse<Map<String, Object>> health() {
        return ApiResponse.success(Map.of("status", "UP", "features", Map.of("moviePosters", true)));
    }

    @GetMapping("/api/validation-demo")
    public ApiResponse<Map<String, String>> validationDemo(
            @RequestParam @NotBlank String value) {
        return ApiResponse.success(Map.of("value", value));
    }
}
