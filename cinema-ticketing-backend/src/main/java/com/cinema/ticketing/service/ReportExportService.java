package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.dto.ReportFilter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Service
public class ReportExportService {
    private static final int MAX_ROWS = 50000;
    private static final int PAGE_SIZE = 500;
    private final JdbcTemplate jdbc;
    private final OccupancyReportService occupancy;
    public ReportExportService(JdbcTemplate jdbc, OccupancyReportService occupancy) {
        this.jdbc = jdbc;
        this.occupancy = occupancy;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public byte[] sales(ReportFilter filter) {
        if (count(filter, true) + count(filter, false) > MAX_ROWS) {
            throw new BusinessException(400, "明细超过 50000 条，请缩小日期范围或筛选影院/影片");
        }
        StringBuilder csv = new StringBuilder("\ufeff");
        line(csv, "数据模式", "事件类型", "统计日", "事件时间（北京时间）", "记录ID", "订单号", "支付流水号",
                "影院", "影片", "影厅", "场次ID", "放映时间（北京时间）", "已支付金额", "退款金额", "毛售出票数", "订单票项数", "订单状态", "记录状态");
        appendEvents(csv, filter, true);
        appendEvents(csv, filter, false);
        return csv.toString().getBytes(StandardCharsets.UTF_8);
    }

    public byte[] occupancy(ReportFilter filter) {
        var report = occupancy.occupancy(filter);
        StringBuilder csv = new StringBuilder("\ufeff");
        line(csv, "数据模式", "日期口径", "放映日", "场次ID", "开场时间（北京时间）", "影院", "影片", "影厅",
                "有效票数", "可售座位数", "容量来源", "上座率（比例）");
        for (var row : report.items()) {
            line(csv, "模拟支付数据", "放映日", row.date(), row.screeningId(), row.startTime(), row.cinemaName(),
                    row.movieTitle(), row.hallName(), row.effectiveTicketCount(), row.sellableSeatCount(),
                    row.capacitySource().equals("UNKNOWN") ? "历史容量未知" : "首次锁座快照",
                    row.occupancyRate());
        }
        return csv.toString().getBytes(StandardCharsets.UTF_8);
    }

    private long count(ReportFilter filter, boolean payment) {
        Long value = jdbc.queryForObject("SELECT COUNT(*)" + fromEvents(filter, payment), Long.class, filter.parameters().toArray());
        return value == null ? 0 : value;
    }

    private void appendEvents(StringBuilder csv, ReportFilter filter, boolean payment) {
        String time = payment ? "e.paid_at" : "e.refunded_at";
        String sql = "SELECT e.id,e.amount,e.status event_status," + time + " event_time,"
                + "o.order_no,o.status order_status,s.id screening_id,s.start_time,c.name cinema_name,"
                + "m.title movie_title,h.name hall_name,"
                + (payment ? "e.payment_no" : "(SELECT p.payment_no FROM payment_transaction p WHERE p.order_id=o.id)")
                + " payment_no,(SELECT COUNT(*) FROM order_item oi WHERE oi.order_id=o.id) ticket_count"
                + fromEvents(filter, payment) + " ORDER BY e.id LIMIT ? OFFSET ?";
        for (int offset = 0; ; offset += PAGE_SIZE) {
            List<Object> parameters = new ArrayList<>(filter.parameters());
            parameters.add(PAGE_SIZE);
            parameters.add(offset);
            List<Map<String, Object>> rows = jdbc.queryForList(sql, parameters.toArray());
            for (var row : rows) {
                String eventTime = row.get("event_time").toString();
                line(csv, "模拟支付数据", payment ? "支付日" : "退款处理日", eventTime.substring(0, 10), eventTime,
                        row.get("id"), row.get("order_no"), row.get("payment_no"), row.get("cinema_name"),
                        row.get("movie_title"), row.get("hall_name"), row.get("screening_id"), row.get("start_time"),
                        payment ? row.get("amount") : "0.00", payment ? "0.00" : row.get("amount"),
                        payment ? row.get("ticket_count") : 0, row.get("ticket_count"), row.get("order_status"), row.get("event_status"));
            }
            if (rows.size() < PAGE_SIZE) break;
        }
    }

    private String fromEvents(ReportFilter filter, boolean payment) {
        String time = payment ? "e.paid_at" : "e.refunded_at";
        return " FROM " + (payment ? "payment_transaction" : "refund_record")
                + " e JOIN ticket_order o ON o.id=e.order_id" + SalesReportService.DIMENSIONS
                + " WHERE e.status='" + (payment ? "SUCCESS" : "REFUNDED") + "' AND " + time + ">=? AND " + time
                + "<?" + filter.dimensionSql();
    }

    static void line(StringBuilder csv, Object... values) {
        for (int index = 0; index < values.length; index++) {
            if (index > 0) csv.append(',');
            String value = values[index] == null ? "" : values[index].toString();
            String trimmed = value.stripLeading();
            if ((!trimmed.isEmpty() && "=+-@".indexOf(trimmed.charAt(0)) >= 0)
                    || (!value.isEmpty() && Character.isISOControl(value.charAt(0)))) value = "'" + value;
            csv.append('"').append(value.replace("\"", "\"\"")).append('"');
        }
        csv.append("\r\n");
    }
}
