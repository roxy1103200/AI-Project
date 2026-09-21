package com.cinema.ticketing.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.util.List;

public record CreateOrderRequest(
        @NotNull @Positive Long screeningId,
        @NotEmpty List<@NotNull @Positive Long> seatIds,
        @NotBlank String requestId) {
}
