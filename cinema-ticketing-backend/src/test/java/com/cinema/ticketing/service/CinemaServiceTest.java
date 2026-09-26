package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.dto.CinemaSaveRequest;
import com.cinema.ticketing.entity.Cinema;
import com.cinema.ticketing.mapper.CinemaMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CinemaServiceTest {

    private CinemaMapper mapper;
    private CinemaService service;

    @BeforeEach
    void setUp() {
        mapper = mock(CinemaMapper.class);
        service = new CinemaService(mapper);
    }

    @Test
    void missingCinemaReturnsNotFound() {
        BusinessException exception = assertThrows(BusinessException.class, () -> service.find(99));
        assertEquals(404, exception.getCode());
    }

    @Test
    void updateSavesTrimmedValues() {
        Cinema existing = new Cinema();
        existing.setId(7L);
        when(mapper.findById(7)).thenReturn(existing);

        service.update(7, new CinemaSaveRequest("  星光影院  ", "  电影路 1 号  ", "  021-1234  ", "ACTIVE"));

        ArgumentCaptor<Cinema> saved = ArgumentCaptor.forClass(Cinema.class);
        verify(mapper).update(saved.capture());
        assertEquals(7L, saved.getValue().getId());
        assertEquals("星光影院", saved.getValue().getName());
        assertEquals("电影路 1 号", saved.getValue().getAddress());
        assertEquals("021-1234", saved.getValue().getPhone());
    }

    @Test
    void cinemaWithHallsCannotBeDeleted() {
        when(mapper.findById(7)).thenReturn(new Cinema());
        when(mapper.countHalls(7)).thenReturn(1);

        BusinessException exception = assertThrows(BusinessException.class, () -> service.delete(7));
        assertEquals(409, exception.getCode());
    }
}
