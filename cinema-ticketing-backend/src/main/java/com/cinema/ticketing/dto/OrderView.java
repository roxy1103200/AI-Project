package com.cinema.ticketing.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

public record OrderView(String orderNo, long userId, long screeningId, BigDecimal totalAmount, String status,
                        LocalDateTime expireAt, LocalDateTime paidAt, LocalDateTime startTime,
                        List<Map<String, Object>> items) {
}
