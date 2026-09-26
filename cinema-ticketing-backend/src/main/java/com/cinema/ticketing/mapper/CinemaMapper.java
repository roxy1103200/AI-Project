package com.cinema.ticketing.mapper;

import com.cinema.ticketing.entity.Cinema;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface CinemaMapper {

    List<Cinema> findAll();

    Cinema findById(@Param("id") long id);

    int insert(Cinema cinema);

    int update(Cinema cinema);

    int countHalls(@Param("cinemaId") long cinemaId);

    int delete(@Param("id") long id);
}
