package com.cinema.ticketing.dto;

import jakarta.validation.constraints.NotBlank;

public record AiChatRequest(
        @NotBlank String sessionId,
        @NotBlank String question) {
}
