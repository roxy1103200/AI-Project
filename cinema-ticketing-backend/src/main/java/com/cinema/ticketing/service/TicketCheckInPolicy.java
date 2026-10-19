package com.cinema.ticketing.service;

import java.time.LocalDateTime;

/** Shared eligibility rules; write operations still validate inside their transaction. */
public final class TicketCheckInPolicy {
    private TicketCheckInPolicy() {}

    public static Decision evaluate(String orderStatus, String screeningStatus, LocalDateTime start,
            Integer duration, LocalDateTime now) {
        if (!"ISSUED".equals(orderStatus)) return new Decision(false, "只有已出票订单可以验票");
        if (!"SCHEDULED".equals(screeningStatus)) return new Decision(false, "场次已取消或资料不可用");
        if (start == null || duration == null) return new Decision(false, "场次时间资料不完整，暂不能判断验票资格");
        if (now.isBefore(start.minusMinutes(15)) || !now.isBefore(start.plusMinutes(duration))) {
            return new Decision(false, "验票开放时间为开场前 15 分钟至影片放映结束");
        }
        return new Decision(true, "请选择实际到场的座位验票");
    }

    public record Decision(boolean allowed, String reason) {}
}
