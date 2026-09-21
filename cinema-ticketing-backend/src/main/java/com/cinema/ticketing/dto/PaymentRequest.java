package com.cinema.ticketing.dto;

import jakarta.validation.constraints.NotBlank;

public record PaymentRequest(@NotBlank String paymentNo) {
}
