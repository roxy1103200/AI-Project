package com.cinema.ticketing.dto;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.util.List;

public record LockSeatsRequest(
        @NotNull @Positive Long screeningId,
        @NotEmpty List<@NotNull @Positive Long> seatIds) {
}
