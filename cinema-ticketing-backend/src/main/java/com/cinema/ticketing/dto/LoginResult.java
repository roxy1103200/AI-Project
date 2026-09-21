package com.cinema.ticketing.dto;

public record LoginResult(String token, Long userId, String username, String role, long expiresInSeconds) {
}
