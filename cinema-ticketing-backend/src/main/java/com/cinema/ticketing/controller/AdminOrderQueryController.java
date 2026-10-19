package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.dto.AdminOrderDetail;
import com.cinema.ticketing.service.AdminOrderQueryService;
import com.cinema.ticketing.service.AuthService;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/admin/orders")
public class AdminOrderQueryController {
    private final AdminOrderQueryService adminOrderQueryService;
    private final AuthService authService;

    public AdminOrderQueryController(AdminOrderQueryService adminOrderQueryService, AuthService authService) {
        this.adminOrderQueryService = adminOrderQueryService;
        this.authService = authService;
    }

    @ModelAttribute
    void disableCaching(jakarta.servlet.http.HttpServletResponse response) {
        response.setHeader(HttpHeaders.CACHE_CONTROL, "no-store");
    }

    @GetMapping("/{orderNo}")
    public ApiResponse<AdminOrderDetail> detail(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable String orderNo) {
        authService.requireAdmin(token);
        return ApiResponse.success(
                adminOrderQueryService.find(orderNo));
    }
}
