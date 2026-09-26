package com.cinema.ticketing.common;

/** SQL predicate shared by public and AI screening lists; aliases are s, m, h, c. */
public final class SellableScreenings {
    private SellableScreenings() {}

    public static final String SCHEDULED_WHERE = "s.status = 'SCHEDULED' AND s.start_time > ? "
            + "AND m.status IN ('UPCOMING', 'ON_SHELF', 'ON_SHOW') "
            + "AND (m.sale_start_time IS NULL OR s.start_time >= m.sale_start_time) "
            + "AND (m.sale_end_time IS NULL OR s.end_time <= m.sale_end_time) "
            + "AND h.status = 'ACTIVE' AND c.status = 'ACTIVE'";

    public static final String WHERE = SCHEDULED_WHERE
            + " AND (m.sale_start_time IS NULL OR m.sale_start_time <= ?) "
            + "AND (m.sale_end_time IS NULL OR m.sale_end_time > ?)";
}
