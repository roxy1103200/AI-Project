package com.cinema.ticketing.service;

import com.cinema.ticketing.common.JdbcTimes;
import java.time.LocalDateTime;
import java.util.Map;

/** One interpretation of order facts for customer pages and the read-only assistant. */
public final class OrderStatusSummary {
    public static final String CONTRACT = "cinema-order-v2";
    private OrderStatusSummary() {}

    public static void decorate(Map<String, Object> order, LocalDateTime now) {
        Number cutoff = (Number) order.get("refund_cutoff_minutes");
        LocalDateTime start = order.get("start_time") == null ? null : JdbcTimes.asLocalDateTime(order.get("start_time"));
        LocalDateTime deadline = cutoff == null || start == null ? null : start.minusMinutes(cutoff.longValue());
        boolean checkedIn = Boolean.TRUE.equals(order.get("has_check_in")) || "1".equals(String.valueOf(order.get("has_check_in")));
        boolean allowed = "ISSUED".equals(order.get("status")) && !checkedIn && deadline != null && now.isBefore(deadline);
        if (order.get("payment_status") == null) order.put("payment_status", "NOT_STARTED");
        order.putIfAbsent("refund_status", null);
        order.putIfAbsent("refund_reason_type", null);
        order.put("contract_version", CONTRACT);
        order.put("refund_deadline", deadline);
        order.put("can_refund", allowed);
        order.put("server_time", now);
        order.put("refund_reason", reason(order, checkedIn, cutoff, allowed));
    }

    private static String reason(Map<String, Object> order, boolean checkedIn, Number cutoff, boolean allowed) {
        String status = String.valueOf(order.get("status"));
        if ("LATE_PAYMENT".equals(order.get("refund_reason_type"))) {
            return "REFUNDED".equals(order.get("refund_status"))
                    ? "订单已取消，迟到付款的补偿退款已确认"
                    : "订单已取消，已收款项正在原路退回，退款结果仍在核对";
        }
        if ("REFUNDING".equals(status)) return "UNKNOWN".equals(order.get("refund_status"))
                ? "退款结果仍在核对，电影票暂不可使用，请勿重复申请"
                : "退款处理中，电影票暂不可使用，请勿重复申请";
        if ("REFUNDED".equals(status)) return "退款已确认，电影票已失效";
        if ("UNPAID".equals(status) && "CLOSING".equals(order.get("payment_status"))) return "正在核对并关闭支付交易，尚未确认取消，请稍后查看订单";
        if ("UNPAID".equals(status)) return "订单尚未支付，无需退款；可前往我的订单取消";
        if ("CANCELLED".equals(status)) return order.get("paid_at") == null
                ? "订单已取消，未收款，无需退款" : "订单已取消，已收款项的处理结果需要核对";
        if (!"ISSUED".equals(status)) return "只有已出票订单可以申请退票";
        if (checkedIn) return "订单中已有电影票验票入场，不能退票";
        if (cutoff == null) return "退票规则暂不可用";
        if (order.get("start_time") == null) return "场次时间资料不完整，暂不能判断退票资格";
        return allowed ? "当前可申请退票" : "已超过退票截止时间";
    }
}
