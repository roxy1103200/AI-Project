package com.cinema.ticketing.payment;

import com.cinema.ticketing.common.BusinessException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import java.math.BigDecimal;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Base64;
import java.util.Map;
import java.util.Set;

@Service
public class PaymentService {
    private static final Logger log = LoggerFactory.getLogger(PaymentService.class);
    private static final SecureRandom RANDOM = new SecureRandom();
    private final PaymentStore store;
    private final PaymentChannel channel;
    private final PaymentProperties properties;
    private final PaymentSeatRelease seats;

    public PaymentService(PaymentStore store, PaymentChannel channel, PaymentProperties properties, PaymentSeatRelease seats) {
        this.store = store; this.channel = channel; this.properties = properties; this.seats = seats;
    }

    public boolean manages(String orderNo) { return store.findByOrder(orderNo).isPresent(); }

    public PaymentStore.View start(long userId, String orderNo) {
        properties.requireEnabled();
        byte[] random = new byte[32]; RANDOM.nextBytes(random);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(random);
        PaymentStore.Payment payment = store.prepare(userId, orderNo, properties, token);
        return store.view(userId, orderNo, "SUCCESS".equals(payment.status()) ? null : "/api/payments/checkout/" + token);
    }

    public String cashier(String token) { return channel.cashier(store.consumeCheckout(token)); }
    public PaymentStore.View status(long userId, String orderNo) { return store.view(userId, orderNo, null); }

    public PaymentStore.View synchronize(long userId, String orderNo) {
        store.view(userId, orderNo, null);
        store.findByOrder(orderNo).ifPresent(payment -> reconcile(payment.id()));
        return status(userId, orderNo);
    }

    public void cancel(long userId, String orderNo) {
        PaymentStore.Payment payment = store.requestClose(orderNo, userId, false);
        if (payment.closing()) reconcile(payment.id());
    }

    public boolean cancelOverdue(String orderNo) {
        PaymentStore.Payment payment = store.requestClose(orderNo, null, true);
        if (payment.closing()) reconcile(payment.id());
        return "CANCELLED".equals(store.find(payment.id()).orderStatus());
    }

    public void reconcile(long paymentId) {
        PaymentStore.Payment snapshot = store.find(paymentId);
        if (Set.of("SUCCESS", "CLOSED").contains(snapshot.status())) return;
        if (!snapshot.closing() && !snapshot.expireAt().isAfter(PaymentStore.now())) {
            snapshot = store.requestClose(snapshot.orderNo(), null, true);
        }
        String lease = store.claimPayment(paymentId);
        if (lease == null) return;
        String error = null;
        try {
            PaymentStore.Payment payment = store.find(paymentId);
            if (payment.closing() && payment.checkoutIssuedAt() == null) {
                seats.release(store.confirmClosed(paymentId));
                return;
            }
            PaymentChannel.Trade trade = channel.query(payment);
            if (trade.paid()) {
                seats.release(store.confirmPaid(payment.paymentNo(), trade));
            } else if (payment.closing()) {
                if ("WAIT_BUYER_PAY".equals(trade.status())) {
                    channel.close(payment);
                    seats.release(store.confirmClosed(paymentId));
                } else if ("TRADE_CLOSED".equals(trade.status()) && trade.paidAt() != null) {
                    // A console refund may close a previously paid trade. Preserve occupancy for manual reconciliation.
                    throw new PaymentChannel.Unavailable("CLOSED_WITH_PAYMENT_REVIEW");
                } else if ("TRADE_CLOSED".equals(trade.status())
                        || ("NOT_FOUND".equals(trade.status()) && PaymentStore.now().isAfter(payment.expireAt().plusSeconds(10)))) {
                    seats.release(store.confirmClosed(paymentId));
                }
            }
        } catch (RuntimeException exception) {
            error = errorCode(exception);
            log.warn("支付对账待重试：支付单 {}，原因 {}", snapshot.paymentNo(), error);
        } finally { store.finishPaymentCheck(paymentId, lease, error); }
    }

    public void refund(long userId, String orderNo, String reason) {
        PaymentStore.Refund refund = store.prepareRefund(userId, orderNo, reason);
        reconcileRefund(refund.id());
    }

    public void reconcileRefund(long refundId) {
        PaymentStore.Refund snapshot = store.findRefund(refundId);
        String lease = store.claimRefund(refundId);
        if (lease == null) return;
        String error = null;
        try {
            PaymentStore.Payment payment = store.find(snapshot.paymentId());
            boolean succeeded = !"PENDING".equals(snapshot.status()) && channel.refundSucceeded(payment, snapshot);
            if (!succeeded) succeeded = channel.refund(payment, snapshot);
            if (succeeded) {
                store.confirmRefund(refundId);
                seats.release(store.find(payment.id()));
            } else error = "REFUND_CONFIRMING";
        } catch (RuntimeException exception) {
            error = errorCode(exception);
            log.warn("退款待核对：退款单 {}，原因 {}", snapshot.refundNo(), error);
        } finally { store.finishRefundCheck(refundId, lease, error); }
    }

    public void notification(Map<String, String> parameters) {
        if (!channel.verify(parameters)) throw new BusinessException(400, "支付通知验签失败");
        PaymentStore.Payment payment = store.find(parameters.get("out_trade_no"));
        if (!payment.appId().equals(parameters.get("app_id")) || !payment.sellerId().equals(parameters.get("seller_id"))
                || !"SANDBOX".equals(payment.environment())) throw new BusinessException(400, "支付通知身份不一致");
        BigDecimal amount = new BigDecimal(parameters.getOrDefault("total_amount", "0"));
        if (payment.amount().compareTo(amount) != 0) throw new BusinessException(400, "支付通知金额不一致");
        String status = parameters.get("trade_status");
        if (!Set.of("TRADE_SUCCESS", "TRADE_FINISHED", "WAIT_BUYER_PAY", "TRADE_CLOSED").contains(status)) {
            throw new BusinessException(400, "支付通知状态不支持");
        }
        if ("TRADE_SUCCESS".equals(status) || "TRADE_FINISHED".equals(status)) {
            LocalDateTime paidAt = LocalDateTime.parse(parameters.get("gmt_payment"), DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
            seats.release(store.confirmPaid(payment.paymentNo(), new PaymentChannel.Trade(status, payment.paymentNo(),
                    parameters.get("trade_no"), amount, paidAt)));
        }
        // Closed notifications can also describe a full refund; never overwrite a received payment here.
        store.recordNotice(payment, parameters.get("notify_id"), status);
    }

    private String errorCode(RuntimeException exception) {
        return exception instanceof PaymentChannel.Unavailable unavailable ? unavailable.code() : "LOCAL_RECONCILE_FAILED";
    }
}
