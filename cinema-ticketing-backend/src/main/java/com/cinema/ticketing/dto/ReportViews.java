package com.cinema.ticketing.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

public final class ReportViews {
    private ReportViews() {}

    public record Metadata(LocalDate from, LocalDate to, String timeZone, String dataMode,
            String currency, LocalDateTime generatedAt, Map<String, String> dateBasis) {
        public static Metadata of(ReportFilter filter, Map<String, String> basis) {
            return new Metadata(filter.from(), filter.to(), "Asia/Shanghai", "SIMULATED", "CNY",
                    LocalDateTime.now(ReportFilter.ZONE), basis);
        }
    }

    public record SalesSummary(@JsonFormat(shape = JsonFormat.Shape.STRING) BigDecimal paidAmount,
            @JsonFormat(shape = JsonFormat.Shape.STRING) BigDecimal refundAmount,
            @JsonFormat(shape = JsonFormat.Shape.STRING) BigDecimal netAmount, long grossTicketCount) {}
    public record SalesRow(LocalDate date, long cinemaId, String cinemaName, long movieId, String movieTitle,
            @JsonFormat(shape = JsonFormat.Shape.STRING) BigDecimal paidAmount,
            @JsonFormat(shape = JsonFormat.Shape.STRING) BigDecimal refundAmount, long grossTicketCount) {}
    public record Sales(Metadata metadata, SalesSummary summary, List<SalesRow> items) {}

    public record OccupancyRow(long screeningId, LocalDate date, LocalDateTime startTime,
            long cinemaId, String cinemaName, long movieId, String movieTitle, String hallName,
            long effectiveTicketCount, Integer sellableSeatCount, String capacitySource, BigDecimal occupancyRate) {}
    public record OccupancySummary(long screeningCount, long effectiveTicketCount, long knownSellableSeatCount,
            long unknownCapacityScreenings, BigDecimal occupancyRate) {}
    public record Occupancy(Metadata metadata, OccupancySummary summary,
            List<OccupancyRow> items, List<OccupancyRow> popular) {}
}
