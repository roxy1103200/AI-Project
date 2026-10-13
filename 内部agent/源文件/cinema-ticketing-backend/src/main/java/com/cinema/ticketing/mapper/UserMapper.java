package com.cinema.ticketing.mapper;

import com.cinema.ticketing.entity.UserAccount;

import org.apache.ibatis.annotations.Param;

public interface UserMapper {

    UserAccount findByUsername(String username);

    UserAccount findById(long id);

    int insert(UserAccount userAccount);

    UserAccount findByIdWithPassword(long id);

    int revokeSessions(@Param("id") long id, @Param("version") long version);

    int changePassword(
            @Param("id") long id,
            @Param("passwordHash") String passwordHash,
            @Param("version") long version);
}
