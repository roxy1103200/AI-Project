package com.cinema.ticketing.mapper;

import com.cinema.ticketing.auth.UserAccount;

public interface UserMapper {

    UserAccount findByUsername(String username);

    int insert(UserAccount userAccount);
}
