package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;

import java.time.LocalDate;

/** Inclusive Beijing calendar dates and optional half-open hour bounds. */
public record AiDateWindow(
        LocalDate releaseFrom,
        LocalDate releaseTo,
        LocalDate screeningFrom,
        LocalDate screeningTo,
        Integer hourFrom,
        Integer hourTo) {
    public static final AiDateWindow EMPTY = new AiDateWindow(null, null, null, null, null, null);

    public AiDateWindow {
        validateDates(releaseFrom, releaseTo);
        validateDates(screeningFrom, screeningTo);
        if ((hourFrom == null) != (hourTo == null)
                || (hourFrom != null && (hourFrom < 0 || hourTo > 24 || hourFrom >= hourTo))) {
            throw new BusinessException(400, "场次时段无效");
        }
    }

    private static void validateDates(LocalDate from, LocalDate to) {
        if ((from == null) != (to == null) || (from != null && from.isAfter(to))) {
            throw new BusinessException(400, "请提供有效且完整的起止日期");
        }
    }
}
