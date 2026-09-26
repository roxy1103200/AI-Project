package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.dto.CinemaSaveRequest;
import com.cinema.ticketing.entity.Cinema;
import com.cinema.ticketing.mapper.CinemaMapper;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class CinemaService {

    private final CinemaMapper cinemaMapper;

    public CinemaService(CinemaMapper cinemaMapper) {
        this.cinemaMapper = cinemaMapper;
    }

    @Cacheable(cacheNames = "cinemaList")
    public List<Cinema> list() {
        return cinemaMapper.findAll();
    }

    @Cacheable(cacheNames = "cinemaDetail", key = "#id")
    public Cinema find(long id) {
        Cinema cinema = cinemaMapper.findById(id);
        if (cinema == null) {
            throw new BusinessException(404, "影院不存在");
        }
        return cinema;
    }

    @Transactional
    @CacheEvict(cacheNames = {"cinemaList", "cinemaDetail"}, allEntries = true)
    public long create(CinemaSaveRequest request) {
        Cinema cinema = toCinema(null, request);
        cinemaMapper.insert(cinema);
        return cinema.getId();
    }

    @Transactional
    @CacheEvict(cacheNames = {"cinemaList", "cinemaDetail"}, allEntries = true)
    public void update(long id, CinemaSaveRequest request) {
        requireCinema(id);
        cinemaMapper.update(toCinema(id, request));
    }

    @Transactional
    @CacheEvict(cacheNames = {"cinemaList", "cinemaDetail"}, allEntries = true)
    public void delete(long id) {
        requireCinema(id);
        if (cinemaMapper.countHalls(id) > 0) {
            throw new BusinessException(409, "影院已配置影厅，请先处理影厅后再删除");
        }
        try {
            cinemaMapper.delete(id);
        } catch (DataIntegrityViolationException exception) {
            throw new BusinessException(409, "影院仍有关联数据，无法删除");
        }
    }

    private void requireCinema(long id) {
        if (cinemaMapper.findById(id) == null) {
            throw new BusinessException(404, "影院不存在");
        }
    }

    private Cinema toCinema(Long id, CinemaSaveRequest request) {
        Cinema cinema = new Cinema();
        cinema.setId(id);
        cinema.setName(request.name().trim());
        cinema.setAddress(request.address().trim());
        cinema.setPhone(request.phone() == null || request.phone().isBlank() ? null : request.phone().trim());
        cinema.setStatus(request.status());
        return cinema;
    }
}
