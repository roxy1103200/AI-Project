package com.cinema.ticketing.dto;

import com.cinema.ticketing.entity.UserAccount;

public record PublicAccount(Long id, String username, String phone, String role) {

    public static PublicAccount from(UserAccount account) {
        return new PublicAccount(account.getId(), account.getUsername(), account.getPhone(), account.getRole());
    }
}
