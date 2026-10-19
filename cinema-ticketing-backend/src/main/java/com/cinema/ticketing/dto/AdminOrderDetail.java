package com.cinema.ticketing.dto;

import java.time.OffsetDateTime;
import java.util.List;

/** Explicit read-only contract: never serialize database rows or payment credentials. */
public record AdminOrderDetail(Order order, Customer customer, Screening screening, List<Ticket> tickets,
        Payment payment, List<Receipt> receipts, List<Refund> refunds, Eligibility eligibility,
        Diagnostics diagnostics, List<Event> events, List<String> dataWarnings,
        OffsetDateTime serverTime, String timeZone) {
    public record Order(long id, String orderNo, String status, String totalAmount, int ticketCount,
            OffsetDateTime createdAt, OffsetDateTime expiresAt, OffsetDateTime paidAt, String description) {}
    public record Customer(Long id, String username) {}
    public record Screening(Long id, Long movieId, String movieTitle, String cinemaName, String hallName,
            String status, Integer durationMinutes, OffsetDateTime startTime, OffsetDateTime viewingEndTime) {}
    public record Ticket(long id, Long seatId, String seatCode, String price, String status,
            OffsetDateTime checkedInAt, Long checkedInBy, String checkedInByName) {}
    public record Payment(String paymentNo, String status, String channel, String environment, String tradeNo,
            String amount, OffsetDateTime expiresAt, OffsetDateTime checkoutIssuedAt,
            OffsetDateTime closeRequestedAt, String closeReason, OffsetDateTime paidAt,
            OffsetDateTime confirmedAt, OffsetDateTime lastQueryAt, OffsetDateTime nextCheckAt, String lastErrorCode) {}
    public record Receipt(String paymentNo, String tradeNo, String amount, String status,
            String channel, String environment, OffsetDateTime paidAt) {}
    public record Refund(long id, String refundNo, String amount, String reason, String status, String channel,
            String environment, String reasonType, String policyVersion, int attempts,
            OffsetDateTime requestedAt, OffsetDateTime refundedAt, OffsetDateTime nextCheckAt, String lastErrorCode) {}
    public record Eligibility(boolean canCheckIn, String checkInReason, boolean canRefund,
            OffsetDateTime refundDeadline, String refundReason) {}
    public record Identity(String appId, String sellerId, String environment) {}
    public record Issue(String code, String severity, String message) {}
    public record Diagnostics(String configurationMatch, Identity storedIdentity, Identity currentIdentity,
            List<Issue> issues) {}
    public record Event(String type, String label, OffsetDateTime at, String source) {}
}
