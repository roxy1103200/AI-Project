package com.cinema.ticketing.dto;

public record CurrentSession(long userId, String username, String role, long expiresInSeconds) {
}
