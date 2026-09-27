package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.TicketCheckInService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/admin/tickets")
public class TicketCheckInController {
    private final TicketCheckInService tickets;
    private final AuthService auth;

    public TicketCheckInController(TicketCheckInService tickets, AuthService auth) { this.tickets = tickets; this.auth = auth; }

    @GetMapping("/{orderNo}")
    public ApiResponse<?> lookup(@RequestHeader("X-Auth-Token") String token, @PathVariable @Size(max = 64) String orderNo) {
        auth.requireAdmin(token);
        return ApiResponse.success(tickets.lookup(orderNo));
    }

    @PostMapping("/{orderNo}/check-in")
    public ApiResponse<?> checkIn(@RequestHeader("X-Auth-Token") String token, @PathVariable @Size(max = 64) String orderNo,
            @Valid @RequestBody CheckInInput input) {
        auth.requireAdmin(token);
        return ApiResponse.success(tickets.checkIn(orderNo, input.itemIds(), auth.requireUserId(token)));
    }

    public record CheckInInput(@NotEmpty @Size(max = 6) List<@NotNull @Positive Long> itemIds) {}
}
