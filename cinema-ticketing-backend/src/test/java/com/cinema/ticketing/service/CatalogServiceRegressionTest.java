package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.HashMap;
import java.util.Map;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class CatalogServiceRegressionTest {
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final CatalogService service = new CatalogService(jdbc);

    @Test
    void missingDetailReturnsNotFound() {
        when(jdbc.queryForMap(anyString(), any(Object[].class)))
                .thenThrow(new EmptyResultDataAccessException(1));
        assertEquals(404, assertThrows(BusinessException.class,
                () -> service.find("movies", 999)).getCode());
    }

    @Test
    void missingUpdateAndDeleteDoNotReportSuccess() {
        assertEquals(404, assertThrows(BusinessException.class,
                () -> service.update("movies", 999, movie())).getCode());
        assertEquals(404, assertThrows(BusinessException.class,
                () -> service.delete("movies", 999)).getCode());
    }

    @Test
    void referencedMovieCannotBeDeleted() {
        when(jdbc.update(anyString(), any(Object[].class)))
                .thenThrow(new DataIntegrityViolationException("foreign key"));
        BusinessException error = assertThrows(BusinessException.class,
                () -> service.delete("movies", 7));
        assertEquals(409, error.getCode());
    }

    @Test
    void invalidMovieIsRejectedBeforeDatabaseWrite() {
        for (Map<String, Object> invalid : List.<Map<String, Object>>of(
                Map.of("title", " ", "duration", 90, "status", "ON_SHELF"),
                Map.of("title", "影片", "duration", -1, "status", "ON_SHELF"),
                Map.of("title", "影片", "duration", 90.5, "status", "ON_SHELF"),
                Map.of("title", "影片", "duration", 90, "status", "INVALID"),
                Map.of("title", "影片", "duration", 90),
                Map.of("title", "影片", "duration", 90, "status", "ON_SHELF", "release_date", "2026-02-30"))) {
            assertEquals(400, assertThrows(BusinessException.class,
                    () -> service.create("movies", invalid)).getCode());
        }
        verifyNoInteractions(jdbc);
    }

    private Map<String, Object> movie() {
        Map<String, Object> values = new HashMap<>();
        values.put("title", "测试影片");
        values.put("duration", 90);
        values.put("status", "ON_SHELF");
        return values;
    }
}
