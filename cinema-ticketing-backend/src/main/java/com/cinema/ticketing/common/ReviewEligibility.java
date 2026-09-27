package com.cinema.ticketing.common;

/** Shared public visibility and viewing qualification, with cinema times in UTC+8. */
public final class ReviewEligibility {
    private ReviewEligibility() {}
    public static final String TICKET = "ro.status='ISSUED' AND ri.ticket_status IN ('ISSUED','VALID') "
            + "AND rs.status='SCHEDULED' AND (ri.checked_in_at IS NOT NULL "
            + "OR DATE_ADD(rs.start_time, INTERVAL rm.duration MINUTE)<=DATE_ADD(UTC_TIMESTAMP(), INTERVAL 8 HOUR))";
    public static final String QUALIFIED = "EXISTS(SELECT 1 FROM ticket_order ro JOIN screening rs ON rs.id=ro.screening_id "
            + "JOIN movie rm ON rm.id=rs.movie_id JOIN order_item ri ON ri.order_id=ro.id "
            + "WHERE ro.user_id=r.user_id AND rs.movie_id=r.movie_id AND " + TICKET + ")";
    public static final String WHERE = "r.status='APPROVED' AND " + QUALIFIED;
}
