package com.cinema.ticketing.dto;

import com.cinema.ticketing.common.BusinessException;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;

/** Calendar dates are inclusive and always describe Beijing business time. */
public record ReportFilter(LocalDate from, LocalDate to, Long cinemaId, Long movieId) {
    public static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");

    public ReportFilter {
        if (from == null || to == null || from.isAfter(to) || ChronoUnit.DAYS.between(from, to) >= 31
                || to.getYear() > 9998 || from.getYear() < 1970) {
            throw new BusinessException(400, "请选择有效日期范围，起止日期均包含，最多查询 31 天");
        }
        if ((cinemaId != null && cinemaId <= 0) || (movieId != null && movieId <= 0)) {
            throw new BusinessException(400, "影院和影片编号必须为正整数");
        }
    }

    public LocalDateTime start() { return from.atStartOfDay(); }
    public LocalDateTime end() { return to.plusDays(1).atStartOfDay(); }

    public String dimensionSql() {
        return (cinemaId == null ? "" : " AND c.id=?") + (movieId == null ? "" : " AND m.id=?");
    }

    public List<Object> parameters() {
        List<Object> values = new ArrayList<>(List.of(start(), end()));
        if (cinemaId != null) values.add(cinemaId);
        if (movieId != null) values.add(movieId);
        return values;
    }
}
