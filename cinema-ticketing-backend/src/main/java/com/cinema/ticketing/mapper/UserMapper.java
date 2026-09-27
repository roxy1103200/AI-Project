package com.cinema.ticketing.mapper;

import com.cinema.ticketing.entity.UserAccount;

public interface UserMapper {

    UserAccount findByUsername(String username);

    UserAccount findById(long id);

    int insert(UserAccount userAccount);
}
