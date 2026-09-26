package com.cinema.ticketing.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record CinemaSaveRequest(
        @NotBlank @Size(max = 128) String name,
        @NotBlank @Size(max = 255) String address,
        @Size(max = 32) String phone,
        @NotBlank @Pattern(regexp = "ACTIVE|INACTIVE", message = "只能是 ACTIVE 或 INACTIVE") String status) {
}
