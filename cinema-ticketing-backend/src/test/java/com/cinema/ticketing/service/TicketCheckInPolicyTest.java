package com.cinema.ticketing.service;

import java.time.LocalDateTime;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class TicketCheckInPolicyTest {
    private static final LocalDateTime START = LocalDateTime.of(2026,10,19,15,0);
    @Test void timeWindowIncludesOpeningAndExcludesMovieEnd() {
        assertFalse(TicketCheckInPolicy.evaluate("ISSUED","SCHEDULED",START,120,START.minusMinutes(15).minusNanos(1)).allowed());
        assertTrue(TicketCheckInPolicy.evaluate("ISSUED","SCHEDULED",START,120,START.minusMinutes(15)).allowed());
        assertTrue(TicketCheckInPolicy.evaluate("ISSUED","SCHEDULED",START,120,START.plusMinutes(120).minusNanos(1)).allowed());
        assertFalse(TicketCheckInPolicy.evaluate("ISSUED","SCHEDULED",START,120,START.plusMinutes(120)).allowed());
    }
    @Test void inactiveTicketsOrMissingScheduleNeverQualify() {
        for (String status : new String[]{"UNPAID","CANCELLED","REFUNDING","REFUNDED"})
            assertFalse(TicketCheckInPolicy.evaluate(status,"SCHEDULED",START,120,START).allowed());
        assertFalse(TicketCheckInPolicy.evaluate("ISSUED","CANCELLED",START,120,START).allowed());
        assertFalse(TicketCheckInPolicy.evaluate("ISSUED","SCHEDULED",null,null,START).allowed());
    }
}
