package com.cinema.ticketing.mapper;

import com.cinema.ticketing.entity.UserAccount;

public interface UserMapper {

    UserAccount findByUsername(String username);

    int insert(UserAccount userAccount);
}
