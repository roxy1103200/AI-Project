package com.cinema.ticketing.payment;

import com.cinema.ticketing.common.BusinessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.function.Supplier;

/** Local transactions only. Channel I/O belongs to PaymentService. */
@Repository
public class PaymentStore {
    private static final String PAYMENT = "SELECT p.*,o.order_no,o.user_id,o.screening_id,o.status order_status,"
            + "s.start_time,s.status screening_status FROM payment_order p JOIN ticket_order o ON o.id=p.order_id "
            + "JOIN screening s ON s.id=o.screening_id ";
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;

    public PaymentStore(JdbcTemplate jdbc, PlatformTransactionManager manager) {
        this.jdbc = jdbc;
        transactions = new TransactionTemplate(manager);
    }

    public Optional<Payment> findByOrder(String orderNo) {
        return jdbc.query(PAYMENT + "WHERE o.order_no=?", this::payment, orderNo).stream().findFirst();
    }

    public Payment find(String paymentNo) {
        return jdbc.query(PAYMENT + "WHERE p.out_trade_no=?", this::payment, paymentNo).stream().findFirst()
                .orElseThrow(() -> new BusinessException(404, "支付单不存在"));
    }

    public Payment find(long paymentId) {
        return jdbc.query(PAYMENT + "WHERE p.id=?", this::payment, paymentId).stream().findFirst()
                .orElseThrow(() -> new BusinessException(404, "支付单不存在"));
    }

    public View view(long userId, String orderNo, String cashierUrl) {
        Order order = order(orderNo, userId, false);
        Optional<Payment> existing = findByOrder(orderNo);
        if (existing.isEmpty()) return new View(orderNo, null, "NOT_STARTED", order.status(), null,
                "SANDBOX", order.expireAt(), now(), cashierUrl, null);
        Payment payment = existing.get();
        Optional<Refund> refund = refund(payment.id());
        return new View(orderNo, payment.paymentNo(), payment.status(), payment.orderStatus(),
                refund.map(Refund::status).orElse(null), payment.environment(), payment.expireAt(), now(),
                cashierUrl, payment.errorCode());
    }

    public Payment prepare(long userId, String orderNo, PaymentProperties configuration, String checkoutToken) {
        return transaction(() -> {
            Order order = order(orderNo, userId, true);
            Optional<Payment> existing = findByOrder(orderNo);
            if (existing.isPresent() && "SUCCESS".equals(existing.get().status())) return existing.get();
            if (!"UNPAID".equals(order.status())) throw new BusinessException(409, "当前订单不能发起支付");
            LocalDateTime deadline = order.expireAt().isBefore(order.startTime()) ? order.expireAt() : order.startTime();
            if (!deadline.isAfter(now().plusSeconds(65))) throw new BusinessException(409, "剩余支付时间不足，请取消后重新下单");
            if (existing.isEmpty()) {
                jdbc.update("INSERT INTO payment_order(order_id,out_trade_no,environment,app_id,seller_id,amount,expire_at,created_at,next_check_at) "
                                + "VALUES(?,?,?,?,?,?,?,?,?)", order.id(), number("P"), configuration.getEnvironment(),
                        configuration.getAlipay().getAppId(), configuration.getAlipay().getSellerId(), order.amount(),
                        deadline, now(), now().plusSeconds(15));
            }
            Payment payment = findByOrder(orderNo).orElseThrow();
            if (payment.closing() || "CLOSED".equals(payment.status())) throw new BusinessException(409, "支付单正在关闭或已关闭");
            if (!payment.appId().equals(configuration.getAlipay().getAppId())
                    || !payment.sellerId().equals(configuration.getAlipay().getSellerId())) {
                throw new BusinessException(503, "该支付单所属沙箱配置已改变，请恢复原应用配置后处理");
            }
            jdbc.update("UPDATE payment_order SET checkout_token_hash=?,checkout_expires_at=? WHERE id=?",
                    hash(checkoutToken), now().plusSeconds(60), payment.id());
            return find(payment.id());
        });
    }

    public Payment consumeCheckout(String token) {
        if (token == null || !token.matches("[A-Za-z0-9_-]{40,100}")) throw new BusinessException(410, "收银台入口已失效");
        return transaction(() -> {
            var rows = jdbc.queryForList("SELECT out_trade_no FROM payment_order WHERE checkout_token_hash=?", String.class, hash(token));
            if (rows.isEmpty()) throw new BusinessException(410, "收银台入口已失效，请重新点击支付");
            Payment payment = lockPayment(find(rows.getFirst()));
            if (payment.closing() || !"UNPAID".equals(payment.orderStatus())
                    || !payment.expireAt().isAfter(now().plusSeconds(60))) throw new BusinessException(410, "订单已停止支付");
            int changed = jdbc.update("UPDATE payment_order SET checkout_token_hash=NULL,checkout_issued_at=?,status='PAYING' "
                    + "WHERE id=? AND checkout_token_hash=? AND checkout_expires_at>?", now(), payment.id(), hash(token), now());
            if (changed != 1) throw new BusinessException(410, "收银台入口已失效，请重新点击支付");
            return find(payment.id());
        });
    }

    public Payment confirmPaid(String paymentNo, PaymentChannel.Trade evidence) {
        return transaction(() -> {
            Payment payment = lockPayment(find(paymentNo));
            validateEvidence(payment, evidence);
            if ("SUCCESS".equals(payment.status())) {
                if (!evidence.tradeNo().equals(payment.tradeNo())) throw new BusinessException(409, "渠道交易号与已确认记录不一致");
                return payment;
            }
            var existing = jdbc.queryForList("SELECT payment_no FROM payment_transaction WHERE order_id=?", String.class, payment.orderId());
            if (!existing.isEmpty()) throw new BusinessException(409, "订单已存在其他收款记录，需要人工核对");
            jdbc.update("INSERT INTO payment_transaction(payment_no,order_id,amount,status,paid_at,channel,environment,"
                            + "channel_trade_no,payment_order_id) VALUES(?,?,?,'SUCCESS',?,'ALIPAY',?,?,?)",
                    number("PAY"), payment.orderId(), payment.amount(), evidence.paidAt(), payment.environment(), evidence.tradeNo(), payment.id());
            jdbc.update("UPDATE payment_order SET status='SUCCESS',channel_trade_no=?,channel_trade_status=?,paid_at=?,confirmed_at=?,"
                    + "checkout_token_hash=NULL,next_check_at=NULL,last_error_code=NULL WHERE id=?",
                    evidence.tradeNo(), evidence.status(), evidence.paidAt(), now(), payment.id());
            jdbc.update("UPDATE ticket_order SET paid_at=? WHERE id=?", evidence.paidAt(), payment.orderId());
            boolean fulfill = "UNPAID".equals(payment.orderStatus()) && !evidence.paidAt().isAfter(payment.expireAt())
                    && payment.startTime().isAfter(now()) && "SCHEDULED".equals(payment.screeningStatus());
            if (fulfill) {
                jdbc.update("UPDATE ticket_order SET status='ISSUED',paid_at=? WHERE id=? AND status='UNPAID'", evidence.paidAt(), payment.orderId());
                jdbc.update("UPDATE order_item SET ticket_status='ISSUED' WHERE order_id=?", payment.orderId());
            } else {
                if ("UNPAID".equals(payment.orderStatus())) {
                    jdbc.update("UPDATE ticket_order SET status='CANCELLED',paid_at=? WHERE id=?", evidence.paidAt(), payment.orderId());
                    jdbc.update("UPDATE order_item SET ticket_status='CANCELLED' WHERE order_id=?", payment.orderId());
                }
                createRefund(payment, "订单无法履约，原路退回已收款项", "LATE_PAYMENT", null);
            }
            return find(payment.id());
        });
    }

    private void validateEvidence(Payment payment, PaymentChannel.Trade trade) {
        if (!trade.paid() || !payment.paymentNo().equals(trade.paymentNo()) || trade.tradeNo() == null || trade.tradeNo().isBlank()
                || trade.tradeNo().length() > 64 || trade.amount() == null || payment.amount().compareTo(trade.amount()) != 0
                || trade.paidAt() == null || trade.paidAt().isAfter(now().plusMinutes(2))) {
            throw new BusinessException(400, "支付通知与订单信息不一致");
        }
    }

    public Payment requestClose(String orderNo, Long userId, boolean overdueOnly) {
        return transaction(() -> {
            order(orderNo, userId, true);
            Payment payment = lockPayment(findByOrder(orderNo).orElseThrow());
            if ("CANCELLED".equals(payment.orderStatus()) || "CLOSED".equals(payment.status())) return payment;
            if (overdueOnly && !"UNPAID".equals(payment.orderStatus())) return payment;
            if (!"UNPAID".equals(payment.orderStatus()) || "SUCCESS".equals(payment.status())) {
                throw new BusinessException(409, "订单已付款，请使用退票流程");
            }
            if (overdueOnly && payment.expireAt().isAfter(now())) return payment;
            jdbc.update("UPDATE payment_order SET status='CLOSING',close_requested_at=COALESCE(close_requested_at,?),"
                    + "close_reason=?,checkout_token_hash=NULL,next_check_at=? WHERE id=? AND status<>'SUCCESS'",
                    now(), overdueOnly ? "EXPIRED" : "USER", now(), payment.id());
            return find(payment.id());
        });
    }

    public Payment confirmClosed(long paymentId) {
        return transaction(() -> {
            Payment payment = lockPayment(find(paymentId));
            if ("SUCCESS".equals(payment.status())) return payment;
            if (!"UNPAID".equals(payment.orderStatus()) && !"CANCELLED".equals(payment.orderStatus())) return payment;
            jdbc.update("UPDATE payment_order SET status='CLOSED',channel_trade_status='TRADE_CLOSED',"
                    + "next_check_at=NULL,checkout_token_hash=NULL,last_error_code=NULL WHERE id=?", payment.id());
            jdbc.update("UPDATE ticket_order SET status='CANCELLED' WHERE id=? AND status='UNPAID'", payment.orderId());
            jdbc.update("UPDATE order_item SET ticket_status='CANCELLED' WHERE order_id=?", payment.orderId());
            return find(payment.id());
        });
    }

    public Refund prepareRefund(long userId, String orderNo, String reason) {
        return transaction(() -> {
            Order order = order(orderNo, userId, true);
            Payment payment = lockPayment(findByOrder(orderNo).orElseThrow());
            Optional<Refund> previous = refund(payment.id());
            if (previous.isPresent()) return previous.get();
            if (!"ISSUED".equals(order.status()) || !"SUCCESS".equals(payment.status())) throw new BusinessException(409, "只有已出票订单可以退票");
            var items = jdbc.queryForList("SELECT id,checked_in_at FROM order_item WHERE order_id=? FOR UPDATE", order.id());
            if (items.stream().anyMatch(item -> item.get("checked_in_at") != null || item.get("CHECKED_IN_AT") != null)) {
                throw new BusinessException(409, "订单已有验票记录，不能退票");
            }
            var policies = jdbc.queryForList("SELECT policy_version,cutoff_minutes FROM refund_policy WHERE enabled=TRUE ORDER BY id DESC LIMIT 1");
            if (policies.isEmpty()) throw new BusinessException(503, "退票规则暂不可用");
            var policy = policies.getFirst();
            if (!order.startTime().isAfter(now().plusMinutes(((Number) policy.get("cutoff_minutes")).longValue()))) {
                throw new BusinessException(409, "已超过退票截止时间");
            }
            String normalized = reason == null || reason.isBlank() ? "用户申请退票" : reason.strip();
            if (normalized.length() > 255) throw new BusinessException(400, "退票原因不能超过255字");
            createRefund(payment, normalized, "CUSTOMER", policy.get("policy_version").toString());
            jdbc.update("UPDATE ticket_order SET status='REFUNDING' WHERE id=? AND status='ISSUED'", order.id());
            return refund(payment.id()).orElseThrow();
        });
    }

    private void createRefund(Payment payment, String reason, String reasonType, String policyVersion) {
        if (refund(payment.id()).isPresent()) return;
        jdbc.update("INSERT INTO refund_record(order_id,amount,reason,status,refund_no,payment_order_id,channel,environment,"
                        + "reason_type,policy_version,requested_at,next_check_at) VALUES(?,?,?,'PENDING',?,?,'ALIPAY',?,?,?,?,?)",
                payment.orderId(), payment.amount(), reason, number("R"), payment.id(), payment.environment(), reasonType, policyVersion, now(), now());
    }

    public Optional<Refund> refund(long paymentId) {
        return jdbc.query("SELECT * FROM refund_record WHERE payment_order_id=?", REFUND_MAPPER, paymentId).stream().findFirst();
    }

    public Refund findRefund(long refundId) {
        return jdbc.query("SELECT * FROM refund_record WHERE id=? AND payment_order_id IS NOT NULL", REFUND_MAPPER, refundId)
                .stream().findFirst().orElseThrow(() -> new BusinessException(404, "退款单不存在"));
    }

    public void confirmRefund(long refundId) {
        transaction(() -> {
            Refund snapshot = findRefund(refundId);
            Payment payment = lockPayment(find(snapshot.paymentId()));
            Refund refund = findRefund(refundId);
            if ("REFUNDED".equals(refund.status())) return null;
            jdbc.update("UPDATE refund_record SET status='REFUNDED',refunded_at=?,next_check_at=NULL,last_error_code=NULL WHERE id=?", now(), refundId);
            if ("REFUNDING".equals(payment.orderStatus())) {
                jdbc.update("UPDATE ticket_order SET status='REFUNDED' WHERE id=? AND status='REFUNDING'", payment.orderId());
                jdbc.update("UPDATE order_item SET ticket_status='REFUNDED' WHERE order_id=?", payment.orderId());
            }
            return null;
        });
    }

    public void recordNotice(Payment payment, String noticeId, String tradeStatus) {
        if (noticeId == null || noticeId.isBlank() || noticeId.length() > 128) throw new BusinessException(400, "通知编号不合法");
        transaction(() -> {
            lockPayment(payment);
            var existing = jdbc.queryForList("SELECT payment_order_id FROM payment_notify_event WHERE app_id=? AND notify_id=?",
                    Long.class, payment.appId(), noticeId);
            if (!existing.isEmpty() && existing.getFirst() != payment.id()) throw new BusinessException(400, "通知编号冲突");
            if (existing.isEmpty()) jdbc.update("INSERT INTO payment_notify_event(app_id,notify_id,payment_order_id,trade_status,processed_at) "
                    + "VALUES(?,?,?,?,?)", payment.appId(), noticeId, payment.id(), tradeStatus, now());
            return null;
        });
    }

    public String claimPayment(long id) {
        String lease = number("L");
        int changed = jdbc.update("UPDATE payment_order SET lease_owner=?,lease_until=?,last_query_at=? WHERE id=? "
                + "AND (lease_until IS NULL OR lease_until<?) AND (last_query_at IS NULL OR last_query_at<?)",
                lease, now().plusSeconds(45), now(), id, now(), now().minusSeconds(3));
        return changed == 1 ? lease : null;
    }

    public void finishPaymentCheck(long id, String lease, String error) {
        jdbc.update("UPDATE payment_order SET lease_owner=NULL,lease_until=NULL,last_error_code=?,"
                + "next_check_at=CASE WHEN status IN ('SUCCESS','CLOSED') THEN NULL ELSE ? END WHERE id=? AND lease_owner=?",
                error, now().plusSeconds(15), id, lease);
    }

    public String claimRefund(long id) {
        String lease = number("L");
        int changed = jdbc.update("UPDATE refund_record SET lease_owner=?,lease_until=?,attempts=attempts+1,status='UNKNOWN',next_check_at=? "
                + "WHERE id=? AND status IN ('PENDING','UNKNOWN') AND attempts<8 AND (lease_until IS NULL OR lease_until<?) "
                + "AND (next_check_at IS NULL OR next_check_at<=?)", lease, now().plusSeconds(45), now().plusSeconds(15), id, now(), now());
        return changed == 1 ? lease : null;
    }

    public void finishRefundCheck(long id, String lease, String error) {
        jdbc.update("UPDATE refund_record SET lease_owner=NULL,lease_until=NULL,last_error_code=?,"
                + "next_check_at=CASE WHEN status='REFUNDED' OR attempts>=8 THEN NULL ELSE ? END WHERE id=? AND lease_owner=?",
                error, now().plusSeconds(30), id, lease);
    }

    public List<Long> pendingPayments() {
        return jdbc.queryForList("SELECT id FROM payment_order WHERE status NOT IN ('SUCCESS','CLOSED') AND next_check_at<=? "
                + "AND (lease_until IS NULL OR lease_until<?) ORDER BY next_check_at LIMIT 50", Long.class, now(), now());
    }

    public List<Long> pendingRefunds() {
        return jdbc.queryForList("SELECT id FROM refund_record WHERE payment_order_id IS NOT NULL AND status IN ('PENDING','UNKNOWN') "
                + "AND attempts<8 AND next_check_at<=? AND (lease_until IS NULL OR lease_until<?) ORDER BY next_check_at LIMIT 50", Long.class, now(), now());
    }

    public List<java.util.Map<String, Object>> exceptions() {
        return jdbc.queryForList("SELECT r.id,r.refund_no,r.status,r.attempts,r.last_error_code,p.out_trade_no,o.order_no,r.requested_at "
                + "FROM refund_record r JOIN payment_order p ON p.id=r.payment_order_id JOIN ticket_order o ON o.id=p.order_id "
                + "WHERE r.status<>'REFUNDED' ORDER BY r.id DESC LIMIT 100");
    }

    public List<java.util.Map<String, Object>> paymentExceptions() {
        return jdbc.queryForList("SELECT p.out_trade_no,o.order_no,p.status,p.last_error_code,p.close_requested_at,p.last_query_at "
                + "FROM payment_order p JOIN ticket_order o ON o.id=p.order_id WHERE p.last_error_code IS NOT NULL "
                + "AND p.status NOT IN ('SUCCESS','CLOSED') ORDER BY p.id DESC LIMIT 100");
    }

    public void retryRefund(long refundId, long adminUserId) {
        transaction(() -> {
            int changed = jdbc.update("UPDATE refund_record SET attempts=0,next_check_at=? WHERE id=? AND payment_order_id IS NOT NULL "
                    + "AND status='UNKNOWN' AND attempts>=8 AND (lease_until IS NULL OR lease_until<?)", now(), refundId, now());
            if (changed != 1) throw new BusinessException(409, "退款正在自动处理或已完成，请刷新状态");
            jdbc.update("INSERT INTO payment_operation_log(action,actor_user_id,refund_id,created_at) VALUES('RETRY_REFUND',?,?,?)",
                    adminUserId, refundId, now());
            return null;
        });
    }

    private Payment lockPayment(Payment snapshot) {
        order(snapshot.orderNo(), null, true);
        jdbc.queryForList("SELECT id FROM payment_order WHERE id=? FOR UPDATE", Long.class, snapshot.id());
        return find(snapshot.id());
    }

    private Order order(String orderNo, Long userId, boolean lock) {
        String sql = "SELECT o.id,o.order_no,o.user_id,o.status,o.total_amount,o.expire_at,s.start_time "
                + "FROM ticket_order o JOIN screening s ON s.id=o.screening_id WHERE o.order_no=?"
                + (userId == null ? "" : " AND o.user_id=?") + (lock ? " FOR UPDATE" : "");
        Object[] args = userId == null ? new Object[]{orderNo} : new Object[]{orderNo, userId};
        return jdbc.query(sql, (rs, row) -> new Order(rs.getLong("id"), rs.getString("order_no"), rs.getLong("user_id"),
                        rs.getString("status"), rs.getBigDecimal("total_amount"), time(rs, "expire_at"), time(rs, "start_time")), args)
                .stream().findFirst().orElseThrow(() -> new BusinessException(404, "订单不存在"));
    }

    private Payment payment(ResultSet rs, int row) throws SQLException {
        return new Payment(rs.getLong("id"), rs.getLong("order_id"), rs.getString("order_no"), rs.getLong("user_id"),
                rs.getString("out_trade_no"), rs.getBigDecimal("amount"), rs.getString("status"), rs.getString("order_status"),
                rs.getString("environment"), rs.getString("app_id"), rs.getString("seller_id"), rs.getString("channel_trade_no"),
                time(rs, "expire_at"), time(rs, "start_time"), rs.getString("screening_status"),
                time(rs, "checkout_issued_at"), time(rs, "close_requested_at"), rs.getString("last_error_code"));
    }

    private static final RowMapper<Refund> REFUND_MAPPER = (rs, row) -> new Refund(rs.getLong("id"), rs.getLong("payment_order_id"),
            rs.getString("refund_no"), rs.getBigDecimal("amount"), rs.getString("status"), rs.getInt("attempts"), rs.getString("reason"));
    private static LocalDateTime time(ResultSet rs, String key) throws SQLException { return rs.getObject(key, LocalDateTime.class); }
    public static LocalDateTime now() { return LocalDateTime.now(PaymentProperties.ZONE); }
    public static String number(String prefix) { return prefix + UUID.randomUUID().toString().replace("-", ""); }
    public static String hash(String text) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException exception) { throw new IllegalStateException(exception); }
    }
    private <T> T transaction(Supplier<T> action) { return transactions.execute(status -> action.get()); }

    private record Order(long id, String orderNo, long userId, String status, BigDecimal amount, LocalDateTime expireAt, LocalDateTime startTime) {}
    public record Payment(long id, long orderId, String orderNo, long userId, String paymentNo, BigDecimal amount, String status,
            String orderStatus, String environment, String appId, String sellerId, String tradeNo, LocalDateTime expireAt,
            LocalDateTime startTime, String screeningStatus, LocalDateTime checkoutIssuedAt, LocalDateTime closeRequestedAt, String errorCode) {
        public Payment {
            // Older sandbox rows may contain whitespace copied with the configured merchant identity.
            appId = appId.replace("\uFEFF", "").strip();
            sellerId = sellerId.replace("\uFEFF", "").strip();
        }
        public boolean closing() { return closeRequestedAt != null; }
    }
    public record Refund(long id, long paymentId, String refundNo, BigDecimal amount, String status, int attempts, String reason) {}
    public record View(String orderNo, String paymentNo, String paymentStatus, String orderStatus, String refundStatus,
            String environment, LocalDateTime expiresAt, LocalDateTime serverTime, String cashierUrl, String errorCode) {}
}
