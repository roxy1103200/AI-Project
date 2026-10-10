package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.dto.ReportFilter;
import com.cinema.ticketing.dto.ReportViews.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.Map;

@Service
public class OccupancyReportService {
    private final JdbcTemplate jdbc;
    public OccupancyReportService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @Transactional(readOnly = true)
    public Occupancy occupancy(ReportFilter filter) {
        var rows = jdbc.query("SELECT s.id,s.start_time,c.id cinema_id,c.name cinema_name,m.id movie_id,m.title movie_title,"
                + "h.name hall_name,cap.sellable_seat_count,COALESCE(t.tickets,0) effective_tickets"
                + " FROM screening s JOIN hall h ON h.id=s.hall_id JOIN cinema c ON c.id=h.cinema_id"
                + " JOIN movie m ON m.id=s.movie_id LEFT JOIN screening_capacity_snapshot cap ON cap.screening_id=s.id"
                + " LEFT JOIN (SELECT o.screening_id,COUNT(oi.id) tickets FROM ticket_order o"
                + " JOIN order_item oi ON oi.order_id=o.id WHERE o.status='ISSUED' AND oi.ticket_status IN ('ISSUED','VALID')"
                + " GROUP BY o.screening_id) t ON t.screening_id=s.id"
                + " WHERE s.status='SCHEDULED' AND s.start_time>=? AND s.start_time<?" + filter.dimensionSql()
                + " ORDER BY s.start_time,s.id LIMIT 20001", (rs, number) -> {
                    LocalDateTime start = rs.getObject("start_time", LocalDateTime.class);
                    Integer capacity = rs.getObject("sellable_seat_count", Integer.class);
                    long count = rs.getLong("effective_tickets");
                    return new OccupancyRow(rs.getLong("id"), start.toLocalDate(), start, rs.getLong("cinema_id"),
                            rs.getString("cinema_name"), rs.getLong("movie_id"), rs.getString("movie_title"),
                            rs.getString("hall_name"), count, capacity, capacity == null ? "UNKNOWN" : "SNAPSHOT", ratio(count, capacity));
                }, filter.parameters().toArray());
        if (rows.size() > 20000) throw new BusinessException(400, "场次超过 20000 条，请缩小日期范围或筛选影院/影片");
        long tickets = rows.stream().mapToLong(OccupancyRow::effectiveTicketCount).sum();
        long capacity = rows.stream().filter(row -> row.sellableSeatCount() != null)
                .mapToLong(OccupancyRow::sellableSeatCount).sum();
        long unknown = rows.stream().filter(row -> row.sellableSeatCount() == null).count();
        var popular = rows.stream().filter(row -> row.effectiveTicketCount() > 0).sorted(Comparator.comparingLong(OccupancyRow::effectiveTicketCount).reversed()
                .thenComparing(OccupancyRow::occupancyRate, Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(OccupancyRow::startTime).thenComparingLong(OccupancyRow::screeningId)).limit(10).toList();
        return new Occupancy(Metadata.of(filter, Map.of("effectiveTicketCount", "SCREENING_DATE", "occupancyRate", "SCREENING_DATE")),
                new OccupancySummary(rows.size(), tickets, capacity, unknown, unknown == 0 ? ratio(tickets, capacity) : null), rows, popular);
    }

    private static BigDecimal ratio(long count, Number capacity) {
        return capacity == null || capacity.longValue() <= 0 ? null
                : BigDecimal.valueOf(count).divide(BigDecimal.valueOf(capacity.longValue()), 6, RoundingMode.HALF_UP);
    }
}
