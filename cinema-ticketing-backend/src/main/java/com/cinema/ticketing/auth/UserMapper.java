package com.cinema.ticketing.auth;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface UserMapper {

    @Select("SELECT id, username, password_hash, phone, role, status FROM users WHERE username = #{username}")
    UserAccount findByUsername(String username);

    @Insert("INSERT INTO users (username, password_hash, phone, role, status) "
            + "VALUES (#{username}, #{passwordHash}, #{phone}, #{role}, #{status})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(UserAccount userAccount);
}
