package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.dto.CreateOrderRequest;
import com.cinema.ticketing.dto.LockSeatsRequest;
import com.cinema.ticketing.dto.OrderView;
import com.cinema.ticketing.dto.PaymentRequest;
import com.cinema.ticketing.dto.RefundRequest;
import com.cinema.ticketing.dto.SeatLockResult;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.OrderService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Positive;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

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
    public ApiResponse<SeatLockResult> lockSeats(
            @RequestHeader("X-Auth-Token") String token,
            @Valid @RequestBody LockSeatsRequest request) {
        authService.requireUserId(token);
        return ApiResponse.success(orderService.lockSeats(token, request.screeningId(), request.seatIds()));
    }

    @PostMapping("/orders")
    public ApiResponse<OrderView> create(
            @RequestHeader("X-Auth-Token") String token,
            @Valid @RequestBody CreateOrderRequest request) {
        long userId = authService.requireUserId(token);
        return ApiResponse.success(orderService.createOrder(userId, token, request));
    }

    @PostMapping("/orders/{orderNo}/pay")
    public ApiResponse<OrderView> pay(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable String orderNo,
            @Valid @RequestBody PaymentRequest request) {
        return ApiResponse.success(orderService.pay(authService.requireUserId(token), token, orderNo,
                request.paymentNo()));
    }

    @PostMapping("/orders/{orderNo}/refund")
    public ApiResponse<OrderView> refund(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable String orderNo,
            @RequestBody(required = false) RefundRequest request) {
        String reason = request == null ? null : request.reason();
        return ApiResponse.success(orderService.refund(authService.requireUserId(token), orderNo, reason));
    }

    @PostMapping("/orders/{orderNo}/cancel")
    public ApiResponse<OrderView> cancel(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable String orderNo) {
        return ApiResponse.success(orderService.cancel(authService.requireUserId(token), orderNo));
    }

    @GetMapping("/orders/{orderNo}")
    public ApiResponse<OrderView> find(
            @RequestHeader("X-Auth-Token") String token,
            @PathVariable String orderNo) {
        return ApiResponse.success(orderService.findOrder(authService.requireUserId(token), orderNo));
    }

    @GetMapping("/orders/{orderNo}/seat-map")
    public ApiResponse<?> seatMap(@RequestHeader("X-Auth-Token") String token,
                                  @PathVariable String orderNo) {
        return ApiResponse.success(orderService.orderSeatMap(authService.requireUserId(token), orderNo));
    }
}
