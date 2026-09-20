package com.cinema.ticketing.order;

import com.cinema.ticketing.auth.AuthService;
import com.cinema.ticketing.common.ApiResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api")
public class OrderController {

    private final AuthService authService;
    private final OrderService orderService;

    public OrderController(AuthService authService, OrderService orderService) {
        this.authService = authService;
        this.orderService = orderService;
    }

    @GetMapping("/screenings/{screeningId}/seats")
    public ApiResponse<?> seats(@PathVariable @Positive long screeningId) {
        return ApiResponse.success(orderService.seats(screeningId));
    }

    @PostMapping("/orders/lock-seats")
    public ApiResponse<OrderService.SeatLockResult> lockSeats(
            @RequestHeader("X-Auth-Token") String token,
            @Valid @RequestBody LockSeatsRequest request) {
        authService.requireUserId(token);
        return ApiResponse.success(orderService.lockSeats(token, request.screeningId(), request.seatIds()));
    }

    @PostMapping("/orders")
    public ApiResponse<OrderService.OrderView> create(
            @RequestHeader("X-Auth-Token") String token,
            @Valid @RequestBody CreateOrderRequest request) {
        long userId = authService.requireUserId(token);
        return ApiResponse.success(orderService.createOrder(userId, token,
                new OrderService.CreateOrderRequest(request.screeningId(), request.seatIds(), request.requestId())));
    }

    @PostMapping("/orders/{orderNo}/pay")
    public ApiResponse<OrderService.OrderView> pay(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable String orderNo) {
        return ApiResponse.success(orderService.pay(authService.requireUserId(token), token, orderNo));
    }

    @PostMapping("/orders/{orderNo}/refund")
    public ApiResponse<OrderService.OrderView> refund(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable String orderNo,
            @RequestBody(required = false) RefundRequest request) {
        String reason = request == null ? null : request.reason();
        return ApiResponse.success(orderService.refund(authService.requireUserId(token), orderNo, reason));
    }

    @GetMapping("/orders/{orderNo}")
    public ApiResponse<OrderService.OrderView> find(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable String orderNo) {
        return ApiResponse.success(orderService.findOrder(authService.requireUserId(token), orderNo));
    }

    public record LockSeatsRequest(
            @NotNull @Positive Long screeningId,
            @NotEmpty List<@NotNull @Positive Long> seatIds) {
    }

    public record CreateOrderRequest(
            @NotNull @Positive Long screeningId,
            @NotEmpty List<@NotNull @Positive Long> seatIds,
            @NotBlank String requestId) {
    }

    public record RefundRequest(String reason) {
    }
}
