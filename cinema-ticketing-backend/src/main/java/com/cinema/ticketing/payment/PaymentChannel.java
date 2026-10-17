package com.cinema.ticketing.payment;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;

public interface PaymentChannel {
    String cashier(PaymentStore.Payment payment);
    Trade query(PaymentStore.Payment payment);
    String close(PaymentStore.Payment payment);
    boolean refund(PaymentStore.Payment payment, PaymentStore.Refund refund);
    boolean refundSucceeded(PaymentStore.Payment payment, PaymentStore.Refund refund);
    boolean verify(Map<String, String> parameters);

    record Trade(String status, String paymentNo, String tradeNo, BigDecimal amount, LocalDateTime paidAt) {
        public boolean paid() { return "TRADE_SUCCESS".equals(status) || "TRADE_FINISHED".equals(status); }
    }

    class Unavailable extends RuntimeException {
        private final String code;
        public Unavailable(String code) { super(code); this.code = code; }
        public String code() { return code; }
    }
}
