package com.cinema.ticketing.service;

import com.cinema.ticketing.common.BusinessException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockMultipartFile;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class MoviePosterServiceTest {

    @TempDir
    Path imageDirectory;

    @Test
    void savesReadsAndRemovesPosterInConfiguredDirectory() throws Exception {
        MoviePosterService service = serviceForExistingMovie();
        byte[] png = Base64.getDecoder().decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII=");

        String url = service.save(7, new MockMultipartFile("file", "image.png", "image/png", png));

        assertEquals("/api/movies/7/poster", url);
        assertTrue(Files.isRegularFile(imageDirectory.resolve("movie-7.png")));
        assertEquals(imageDirectory.resolve("movie-7.png"), service.find(7));

        service.delete(7);
        assertFalse(Files.exists(imageDirectory.resolve("movie-7.png")));
    }

    @Test
    void rejectsNonImageContentEvenWhenFilenameLooksLikeImage() {
        MoviePosterService service = serviceForExistingMovie();
        MockMultipartFile file = new MockMultipartFile("file", "image.png", "image/png", "not an image".getBytes());

        BusinessException exception = assertThrows(BusinessException.class, () -> service.save(7, file));
        assertEquals(400, exception.getCode());
    }

    private MoviePosterService serviceForExistingMovie() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        when(jdbcTemplate.queryForObject(eq("SELECT COUNT(*) FROM movie WHERE id = ?"), eq(Integer.class), eq(7L)))
                .thenReturn(1);
        return new MoviePosterService(jdbcTemplate, imageDirectory.toString());
    }
}
