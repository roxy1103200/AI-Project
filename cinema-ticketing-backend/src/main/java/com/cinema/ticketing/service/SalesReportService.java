package com.cinema.ticketing.service;

import com.cinema.ticketing.dto.ReportFilter;
import com.cinema.ticketing.dto.ReportViews.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class SalesReportService {
    static final String DIMENSIONS = " JOIN screening s ON s.id=o.screening_id"
            + " JOIN hall h ON h.id=s.hall_id JOIN cinema c ON c.id=h.cinema_id JOIN movie m ON m.id=s.movie_id";
    private final JdbcTemplate jdbc;

    public SalesReportService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Sales sales(ReportFilter filter) {
        Map<Key, Totals> grouped = new LinkedHashMap<>();
        // Each monetary fact is aggregated before it can meet a one-to-many ticket relationship.
        accumulate(grouped, query(filter, "p.paid_at", "SUM(p.amount)", "0", "0",
                "payment_transaction p JOIN ticket_order o ON o.id=p.order_id", "p.status='SUCCESS'"));
        accumulate(grouped, query(filter, "r.refunded_at", "0", "SUM(r.amount)", "0",
                "refund_record r JOIN ticket_order o ON o.id=r.order_id", "r.status='REFUNDED'"));
        accumulate(grouped, query(filter, "p.paid_at", "0", "0", "COUNT(oi.id)",
                "payment_transaction p JOIN ticket_order o ON o.id=p.order_id JOIN order_item oi ON oi.order_id=o.id",
                "p.status='SUCCESS'"));
        List<SalesRow> items = grouped.entrySet().stream().map(entry -> entry.getValue().row(entry.getKey()))
                .sorted(Comparator.comparing(SalesRow::date).thenComparingLong(SalesRow::cinemaId)
                        .thenComparingLong(SalesRow::movieId)).toList();
        BigDecimal paid = items.stream().map(SalesRow::paidAmount).reduce(moneyZero(), BigDecimal::add);
        BigDecimal refund = items.stream().map(SalesRow::refundAmount).reduce(moneyZero(), BigDecimal::add);
        return new Sales(Metadata.of(filter, Map.of("paidAmount", "PAYMENT_DATE", "refundAmount", "REFUND_DATE",
                "grossTicketCount", "PAYMENT_DATE")),
                new SalesSummary(paid, refund, paid.subtract(refund), items.stream().mapToLong(SalesRow::grossTicketCount).sum()), items);
    }

    private List<Map<String, Object>> query(ReportFilter filter, String time, String paid, String refund,
            String count, String fact, String status) {
        String sql = "SELECT CAST(" + time + " AS DATE) report_date,c.id cinema_id,c.name cinema_name,"
                + "m.id movie_id,m.title movie_title," + paid + " paid_amount," + refund + " refund_amount,"
                + count + " gross_count FROM " + fact + DIMENSIONS + " WHERE " + status + " AND " + time
                + ">=? AND " + time + "<?" + filter.dimensionSql()
                + " GROUP BY CAST(" + time + " AS DATE),c.id,c.name,m.id,m.title";
        return jdbc.queryForList(sql, filter.parameters().toArray());
    }

    private void accumulate(Map<Key, Totals> grouped, List<Map<String, Object>> rows) {
        for (var row : rows) {
            Key key = new Key(LocalDate.parse(row.get("report_date").toString()),
                    ((Number) row.get("cinema_id")).longValue(), ((Number) row.get("movie_id")).longValue());
            Totals totals = grouped.computeIfAbsent(key, ignored -> new Totals(
                    row.get("cinema_name").toString(), row.get("movie_title").toString()));
            totals.paid = totals.paid.add(new BigDecimal(row.get("paid_amount").toString()));
            totals.refund = totals.refund.add(new BigDecimal(row.get("refund_amount").toString()));
            totals.count += ((Number) row.get("gross_count")).longValue();
        }
    }

    private static BigDecimal moneyZero() { return new BigDecimal("0.00"); }
    private record Key(LocalDate date, long cinemaId, long movieId) {}
    private static final class Totals {
        private final String cinemaName;
        private final String movieTitle;
        private BigDecimal paid = moneyZero();
        private BigDecimal refund = moneyZero();
        private long count;
        private Totals(String cinemaName, String movieTitle) { this.cinemaName = cinemaName; this.movieTitle = movieTitle; }
        private SalesRow row(Key key) {
            return new SalesRow(key.date(), key.cinemaId(), cinemaName, key.movieId(), movieTitle, paid, refund, count);
        }
    }
}
