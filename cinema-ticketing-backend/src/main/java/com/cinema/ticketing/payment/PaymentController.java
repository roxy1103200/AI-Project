package com.cinema.ticketing.payment;

import com.cinema.ticketing.common.ApiResponse;
import com.cinema.ticketing.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class PaymentController {
    private final AuthService auth;
    private final PaymentService payments;
    private final PaymentStore store;
    private final PaymentProperties properties;
    public PaymentController(AuthService auth, PaymentService payments, PaymentStore store, PaymentProperties properties) {
        this.auth = auth; this.payments = payments; this.store = store; this.properties = properties;
    }

    @GetMapping("/payments/config")
    public ApiResponse<?> config() {
        return ApiResponse.success(Map.of("enabled", properties.isEnabled(), "mockEnabled", properties.isMockEnabled(),
                "environment", properties.getEnvironment()));
    }

    @PostMapping("/orders/{orderNo}/payment")
    public ApiResponse<?> start(@RequestHeader("X-Auth-Token") String token, @PathVariable String orderNo) {
        return ApiResponse.success(payments.start(auth.requireUserId(token), orderNo));
    }

    @GetMapping("/orders/{orderNo}/payment")
    public ApiResponse<?> status(@RequestHeader("X-Auth-Token") String token, @PathVariable String orderNo) {
        return ApiResponse.success(payments.status(auth.requireUserId(token), orderNo));
    }

    @PostMapping("/orders/{orderNo}/payment/sync")
    public ApiResponse<?> synchronize(@RequestHeader("X-Auth-Token") String token, @PathVariable String orderNo) {
        return ApiResponse.success(payments.synchronize(auth.requireUserId(token), orderNo));
    }

    @GetMapping(value = "/payments/checkout/{ticket}", produces = MediaType.TEXT_HTML_VALUE)
    public ResponseEntity<String> checkout(@PathVariable String ticket) {
        try { return html(payments.cashier(ticket), 200); }
        catch (RuntimeException exception) {
            return html("<!doctype html><html lang=zh-CN><meta charset=utf-8><title>支付暂未发起</title>"
                    + "<h1>支付暂未发起</h1><p>入口可能已过期或订单正在处理。请返回影院查看订单后重试。</p><a href=/>返回影院</a></html>", 409);
        }
    }

    private ResponseEntity<String> html(String body, int status) {
        return ResponseEntity.status(status).contentType(MediaType.parseMediaType("text/html;charset=UTF-8"))
                .header(HttpHeaders.CACHE_CONTROL, "no-store").header("Referrer-Policy", "no-referrer")
                .header("X-Content-Type-Options", "nosniff").header("X-Frame-Options", "DENY").body(body);
    }

    @PostMapping(value = "/payments/alipay/notify", produces = MediaType.TEXT_PLAIN_VALUE)
    public ResponseEntity<String> notify(HttpServletRequest request) {
        try {
            if (request.getContentLengthLong() > 65536 || request.getContentType() == null
                    || !request.getContentType().toLowerCase(java.util.Locale.ROOT).startsWith(MediaType.APPLICATION_FORM_URLENCODED_VALUE)) {
                return ResponseEntity.badRequest().body("failure");
            }
            Map<String, String> parameters = new LinkedHashMap<>();
            request.getParameterMap().forEach((key, values) -> {
                if (values.length != 1 || key.length() > 128 || values[0].length() > 16384) throw new IllegalArgumentException();
                parameters.put(key, values[0]);
            });
            if (parameters.size() > 64 || parameters.entrySet().stream()
                    .mapToInt(entry -> entry.getKey().length() + entry.getValue().length()).sum() > 65536) {
                return ResponseEntity.badRequest().body("failure");
            }
            payments.notification(parameters);
            return ResponseEntity.ok().header(HttpHeaders.CACHE_CONTROL, "no-store").body("success");
        } catch (RuntimeException exception) {
            // A non-success response lets Alipay retry; never log the signed form or key material.
            return ResponseEntity.status(503).body("failure");
        }
    }

    @GetMapping("/admin/payments/exceptions")
    public ApiResponse<?> exceptions(@RequestHeader("X-Auth-Token") String token) {
        auth.requireAdmin(token);
        return ApiResponse.success(Map.of("refunds", store.exceptions(), "payments", store.paymentExceptions()));
    }

    @PostMapping("/admin/refunds/{id}/retry")
    public ApiResponse<?> retry(@RequestHeader("X-Auth-Token") String token, @PathVariable long id) {
        auth.requireAdmin(token);
        store.findRefund(id);
        store.retryRefund(id, auth.requireUserId(token));
        payments.reconcileRefund(id);
        return ApiResponse.success(store.findRefund(id));
    }
}
