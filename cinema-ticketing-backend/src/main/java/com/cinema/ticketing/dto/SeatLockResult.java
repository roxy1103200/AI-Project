package com.cinema.ticketing.dto;

import java.time.LocalDateTime;
import java.util.List;

public record SeatLockResult(long screeningId, List<Long> seatIds, LocalDateTime lockedUntil) {
}
