package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.dto.AdminOrderDetail;
import com.cinema.ticketing.dto.AdminOrderDetail.*;
import com.cinema.ticketing.payment.PaymentProperties;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AdminOrderQueryService {
    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    private static final Set<String> TERMINAL_PAYMENTS = Set.of("SUCCESS", "CLOSED");
    private final JdbcTemplate jdbc;
    private final PaymentProperties properties;
    private final Clock clock;

    @Autowired
    public AdminOrderQueryService(JdbcTemplate jdbc, PaymentProperties properties) {
        this(jdbc, properties, Clock.system(ZONE));
    }

    AdminOrderQueryService(JdbcTemplate jdbc, PaymentProperties properties, Clock clock) {
        this.jdbc = jdbc;
        this.properties = properties;
        this.clock = clock;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AdminOrderDetail find(String input) {
        String orderNo = normalizeOrderNo(input);
        var rows = jdbc.queryForList("SELECT o.id,o.order_no,o.user_id,o.screening_id,o.status,o.total_amount,"
                + "o.created_at,o.expire_at,o.paid_at,u.username,s.id linked_screening_id,s.movie_id,s.start_time,"
                + "s.status screening_status,m.title movie_title,m.duration,h.name hall_name,c.name cinema_name "
                + "FROM ticket_order o LEFT JOIN users u ON u.id=o.user_id "
                + "LEFT JOIN screening s ON s.id=o.screening_id LEFT JOIN movie m ON m.id=s.movie_id "
                + "LEFT JOIN hall h ON h.id=s.hall_id LEFT JOIN cinema c ON c.id=h.cinema_id WHERE o.order_no=?", orderNo);
        if (rows.isEmpty()) throw new BusinessException(404, "未找到该订单，请核对完整订单号");
        Map<String, Object> order = rows.getFirst();
        long orderId = id(order, "id");
        OffsetDateTime now = OffsetDateTime.now(clock).atZoneSameInstant(ZONE).toOffsetDateTime();
        List<Ticket> tickets = tickets(orderId);
        var paymentRows = paymentRows(orderId);
        Payment payment = paymentRows.isEmpty() ? null : payment(paymentRows.getFirst());
        List<Receipt> receipts = receipts(orderId);
        List<Refund> refunds = refunds(orderId);
        Eligibility eligibility = eligibility(order, tickets, payment, receipts, refunds, now.toLocalDateTime());
        List<String> warnings = warnings(order, tickets);
        var summary = new Order(orderId, text(order, "order_no"), text(order, "status"), money(order, "total_amount"),
                tickets.size(), instant(order.get("created_at")), time(order, "expire_at"), time(order, "paid_at"), eligibility.refundReason());
        return new AdminOrderDetail(summary, new Customer(number(order, "user_id"), text(order, "username")),
                screening(order), tickets, payment, receipts, refunds, eligibility,
                diagnostics(order, paymentRows, refunds, receipts), events(summary, payment, receipts, refunds, tickets),
                List.copyOf(warnings), now, ZONE.getId());
    }

    private String normalizeOrderNo(String input) {
        String value = input == null ? "" : input.strip();
        if (value.isEmpty() || value.length() > 64 || value.chars().anyMatch(Character::isISOControl)) {
            throw new BusinessException(400, "请输入不超过 64 个字符的完整订单号");
        }
        return value;
    }

    private List<Ticket> tickets(long orderId) {
        return jdbc.queryForList("SELECT i.id,i.seat_id,i.price,i.ticket_status,i.checked_in_at,i.checked_in_by,"
                + "s.seat_code,u.username checked_in_by_name FROM order_item i LEFT JOIN seat s ON s.id=i.seat_id "
                + "LEFT JOIN users u ON u.id=i.checked_in_by WHERE i.order_id=? ORDER BY i.id", orderId).stream()
                .map(row -> new Ticket(id(row, "id"), number(row, "seat_id"), text(row, "seat_code"), money(row, "price"),
                        text(row, "ticket_status"), time(row, "checked_in_at"), number(row, "checked_in_by"), text(row, "checked_in_by_name")))
                .toList();
    }

    private List<Map<String, Object>> paymentRows(long orderId) {
        return jdbc.queryForList("SELECT out_trade_no,status,channel,environment,app_id,seller_id,amount,channel_trade_no,"
                + "expire_at,checkout_issued_at,close_requested_at,close_reason,paid_at,confirmed_at,last_query_at,"
                + "next_check_at,last_error_code FROM payment_order WHERE order_id=?", orderId);
    }

    private Payment payment(Map<String, Object> row) {
        return new Payment(text(row, "out_trade_no"), text(row, "status"), text(row, "channel"), text(row, "environment"),
                text(row, "channel_trade_no"), money(row, "amount"), time(row, "expire_at"), time(row, "checkout_issued_at"),
                time(row, "close_requested_at"), text(row, "close_reason"), time(row, "paid_at"), time(row, "confirmed_at"),
                time(row, "last_query_at"), time(row, "next_check_at"), text(row, "last_error_code"));
    }

    private List<Receipt> receipts(long orderId) {
        return jdbc.queryForList("SELECT payment_no,channel_trade_no,amount,status,channel,environment,paid_at "
                + "FROM payment_transaction WHERE order_id=? ORDER BY id", orderId).stream()
                .map(row -> new Receipt(text(row, "payment_no"), text(row, "channel_trade_no"), money(row, "amount"),
                        text(row, "status"), text(row, "channel"), text(row, "environment"), time(row, "paid_at"))).toList();
    }

    private List<Refund> refunds(long orderId) {
        return jdbc.queryForList("SELECT id,refund_no,amount,reason,status,channel,environment,reason_type,policy_version,"
                + "attempts,requested_at,refunded_at,next_check_at,last_error_code FROM refund_record WHERE order_id=? ORDER BY id", orderId)
                .stream().map(row -> new Refund(id(row, "id"), text(row, "refund_no"), money(row, "amount"), text(row, "reason"),
                        text(row, "status"), text(row, "channel"), text(row, "environment"), text(row, "reason_type"),
                        text(row, "policy_version"), Math.toIntExact(id(row, "attempts")), time(row, "requested_at"),
                        time(row, "refunded_at"), time(row, "next_check_at"), text(row, "last_error_code"))).toList();
    }

    private Screening screening(Map<String, Object> row) {
        OffsetDateTime start = time(row, "start_time");
        Long duration = number(row, "duration");
        return new Screening(number(row, "screening_id"), number(row, "movie_id"), text(row, "movie_title"),
                text(row, "cinema_name"), text(row, "hall_name"), text(row, "screening_status"),
                duration == null ? null : Math.toIntExact(duration), start,
                start == null || duration == null ? null : start.plusMinutes(duration));
    }

    private Eligibility eligibility(Map<String, Object> order, List<Ticket> tickets, Payment payment,
            List<Receipt> receipts, List<Refund> refunds, LocalDateTime now) {
        var facts = new HashMap<>(order);
        var policies = jdbc.queryForList("SELECT cutoff_minutes FROM refund_policy WHERE enabled=TRUE ORDER BY id DESC LIMIT 1");
        facts.put("refund_cutoff_minutes", policies.isEmpty() ? null : policies.getFirst().get("cutoff_minutes"));
        OffsetDateTime start = time(order, "start_time");
        facts.put("start_time", start == null ? null : start.toLocalDateTime());
        facts.put("has_check_in", tickets.stream().anyMatch(ticket -> ticket.checkedInAt() != null));
        facts.put("payment_status", payment == null ? receipts.stream().anyMatch(r -> "SUCCESS".equals(r.status()))
                ? "SUCCESS" : "NOT_STARTED" : payment.status());
        if (!refunds.isEmpty()) {
            facts.put("refund_status", refunds.getLast().status());
            facts.put("refund_reason_type", refunds.getLast().reasonType());
        }
        OrderStatusSummary.decorate(facts, now);
        Long duration = number(order, "duration");
        var checkIn = TicketCheckInPolicy.evaluate(text(order, "status"), text(order, "screening_status"),
                start == null ? null : start.toLocalDateTime(), duration == null ? null : Math.toIntExact(duration), now);
        boolean available = tickets.stream().anyMatch(t -> Set.of("ISSUED", "VALID").contains(t.status()) && t.checkedInAt() == null);
        String reason = checkIn.allowed() && !available ? "本订单没有待验票的有效电影票" : checkIn.reason();
        return new Eligibility(checkIn.allowed() && available, reason, Boolean.TRUE.equals(facts.get("can_refund")),
                offset(facts.get("refund_deadline")), text(facts, "refund_reason"));
    }

    private List<String> warnings(Map<String, Object> row, List<Ticket> tickets) {
        List<String> result = new ArrayList<>();
        if (row.get("username") == null) result.add("购票人历史账号资料缺失，保留用户编号供核对。");
        if (row.get("movie_title") == null || row.get("hall_name") == null || row.get("cinema_name") == null
                || row.get("start_time") == null || row.get("duration") == null) result.add("部分场次或影片关联资料缺失，展示现存订单事实。");
        if (tickets.isEmpty() || tickets.stream().anyMatch(t -> t.seatCode() == null)) result.add("部分影票或座位资料缺失，需要核对历史记录。");
        return result;
    }

    private Diagnostics diagnostics(Map<String, Object> order, List<Map<String, Object>> rows,
            List<Refund> refunds, List<Receipt> receipts) {
        List<Issue> issues = new ArrayList<>();
        String match = "UNKNOWN";
        Identity stored = null;
        var configured = properties.getAlipay();
        Identity current = new Identity(mask(configured.getAppId()), mask(configured.getSellerId()), properties.getEnvironment());
        if (!rows.isEmpty()) {
            var row = rows.getFirst();
            stored = new Identity(mask(text(row, "app_id")), mask(text(row, "seller_id")), text(row, "environment"));
            boolean applicable = "ALIPAY".equals(text(row, "channel")) && !TERMINAL_PAYMENTS.contains(text(row, "status"));
            if (applicable && properties.isEnabled() && !configured.getAppId().isBlank() && !configured.getSellerId().isBlank()) {
                boolean same = clean(text(row, "app_id")).equals(configured.getAppId())
                        && clean(text(row, "seller_id")).equals(configured.getSellerId())
                        && Objects.equals(text(row, "environment"), properties.getEnvironment());
                match = same ? "MATCH" : "MISMATCH";
                if (!same) issues.add(new Issue("CONFIG_MISMATCH", "error", "支付单所属应用或商户配置与当前服务不一致，需要管理员核对；刷新不会修复配置。"));
            }
            String error = text(row, "last_error_code");
            if (error != null && issues.stream().noneMatch(i -> i.code().equals(error))) issues.add(paymentIssue(error));
        }
        for (Refund refund : refunds) {
            if ("UNKNOWN".equals(refund.status()) && refund.attempts() >= 8 && refund.nextCheckAt() == null) {
                issues.add(new Issue("REFUND_REVIEW_REQUIRED", "warning", "退款自动核对已暂停，请前往支付与退款核对模块处理原退款单。"));
            } else if (refund.lastErrorCode() != null) issues.add(paymentIssue(refund.lastErrorCode()));
        }
        String status = text(order, "status");
        if (!Set.of("UNPAID", "PAID", "ISSUED", "CANCELLED", "REFUNDING", "REFUNDED").contains(status)) {
            issues.add(new Issue("UNKNOWN_ORDER_STATUS", "warning", "订单状态未被当前版本识别，保留原始状态供核对。"));
        }
        boolean paid = receipts.stream().anyMatch(r -> "SUCCESS".equals(r.status()));
        boolean missingReceipt = Set.of("PAID", "ISSUED", "REFUNDING", "REFUNDED").contains(status) && !paid;
        boolean unexpectedReceipt = "UNPAID".equals(status) && paid;
        boolean unpaidTicket = !Set.of("PAID", "ISSUED", "REFUNDING", "REFUNDED", "CANCELLED").contains(status)
                && !rows.isEmpty() && "SUCCESS".equals(text(rows.getFirst(), "status"));
        if (missingReceipt || unexpectedReceipt || unpaidTicket) {
            issues.add(new Issue("STATE_REVIEW_REQUIRED", "warning", "订单状态与现存收款记录不一致，需要核对；本页面不会修改状态。"));
        }
        return new Diagnostics(match, stored, current, List.copyOf(issues));
    }

    private Issue paymentIssue(String code) {
        String message = switch (code) {
            case "CONFIG_MISMATCH" -> "支付单所属配置不一致，需要管理员核对。";
            case "CHANNEL_UNAVAILABLE" -> "渠道连接或响应异常，请查看最近核对时间。";
            case "CLOSED_WITH_PAYMENT_REVIEW" -> "交易关闭同时存在付款信息，需要人工核对收款和退款。";
            case "LOCAL_RECONCILE_FAILED" -> "本地支付核对失败，需要结合服务日志排查。";
            default -> "存在支付或退款核对异常，请查看错误码及最近核对记录。";
        };
        return new Issue(code, "warning", message);
    }

    private List<Event> events(Order order, Payment payment, List<Receipt> receipts, List<Refund> refunds, List<Ticket> tickets) {
        List<Event> result = new ArrayList<>();
        addEvent(result, "CREATED", "订单创建", order.createdAt(), "ticket_order.created_at");
        if (payment != null) {
            addEvent(result, "CHECKOUT_ISSUED", "本地已发放收银台页面", payment.checkoutIssuedAt(), "payment_order.checkout_issued_at");
            addEvent(result, "CLOSE_REQUESTED", "申请关闭支付交易", payment.closeRequestedAt(), "payment_order.close_requested_at");
            addEvent(result, "PAYMENT_CONFIRMED", "本地确认收款", payment.confirmedAt(), "payment_order.confirmed_at");
        }
        for (Receipt receipt : receipts) if ("SUCCESS".equals(receipt.status())) addEvent(result, "PAID", "渠道或模拟收款记录", receipt.paidAt(), "payment_transaction.paid_at");
        for (Refund refund : refunds) {
            addEvent(result, "REFUND_REQUESTED", "申请退款 " + Objects.toString(refund.refundNo(), "历史记录"), refund.requestedAt(), "refund_record.requested_at");
            if ("REFUNDED".equals(refund.status())) addEvent(result, "REFUNDED", "确认退款", refund.refundedAt(), "refund_record.refunded_at");
        }
        for (Ticket ticket : tickets) addEvent(result, "CHECKED_IN", "影票验票：" + Objects.toString(ticket.seatCode(), "座位资料缺失"), ticket.checkedInAt(), "order_item.checked_in_at");
        result.sort(Comparator.comparing(Event::at));
        return List.copyOf(result);
    }

    private static void addEvent(List<Event> events, String type, String label, OffsetDateTime at, String source) {
        if (at != null) events.add(new Event(type, label, at, source));
    }

    private static String text(Map<String, Object> row, String key) { return Objects.toString(row.get(key), null); }
    private static Long number(Map<String, Object> row, String key) { return row.get(key) == null ? null : ((Number) row.get(key)).longValue(); }
    private static long id(Map<String, Object> row, String key) { return Objects.requireNonNull(number(row, key)); }
    private static String money(Map<String, Object> row, String key) { return new BigDecimal(row.get(key).toString()).setScale(2).toPlainString(); }
    private static String clean(String value) { return value == null ? "" : value.replace("\uFEFF", "").strip(); }
    private static String mask(String value) { String clean = clean(value); return clean.isEmpty() ? null : "****" + clean.substring(Math.max(0, clean.length() - 4)); }
    private static OffsetDateTime time(Map<String, Object> row, String key) { return offset(row.get(key)); }
    private static OffsetDateTime offset(Object value) {
        if (value == null) return null;
        if (value instanceof OffsetDateTime time) return time.atZoneSameInstant(ZONE).toOffsetDateTime();
        LocalDateTime local = value instanceof Timestamp time ? time.toLocalDateTime() : (LocalDateTime) value;
        return local.atZone(ZONE).toOffsetDateTime();
    }
    private static OffsetDateTime instant(Object value) {
        return value instanceof Timestamp time ? time.toInstant().atZone(ZONE).toOffsetDateTime() : offset(value);
    }
}
