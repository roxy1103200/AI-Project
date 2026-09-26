package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.GlobalExceptionHandler;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.CatalogService;
import com.cinema.ticketing.service.MoviePosterService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.file.Path;
import java.util.Base64;

import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class MoviePosterRoutingTest {
    @TempDir Path directory;
    private MockMvc mvc;
    private final byte[] png = Base64.getDecoder().decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII=");

    @BeforeEach
    void setup() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject("SELECT COUNT(*) FROM movie WHERE id = ?", Integer.class, 7L))
                .thenReturn(1);
        MoviePosterService posters = new MoviePosterService(jdbc, directory.toString());
        AuthService auth = mock(AuthService.class);
        doThrow(new BusinessException(401, "请登录")).when(auth).requireAdmin(isNull());
        mvc = MockMvcBuilders.standaloneSetup(new MoviePosterController(posters, auth),
                        new CatalogController(mock(CatalogService.class), auth, posters))
                .setControllerAdvice(new GlobalExceptionHandler()).build();
    }

    @Test
    void multipartUploadReadReplaceAndDeleteUsePosterRoute() throws Exception {
        upload(png).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.url").value("/api/movies/7/poster"));
        mvc.perform(get("/api/movies/7/poster"))
                .andExpect(status().isOk()).andExpect(content().bytes(png));
        upload("not an image".getBytes()).andExpect(status().isBadRequest());
        mvc.perform(get("/api/movies/7/poster"))
                .andExpect(status().isOk()).andExpect(content().bytes(png));
        upload(png).andExpect(status().isOk());
        mvc.perform(delete("/api/movies/7/poster").header("X-Auth-Token", "admin"))
                .andExpect(status().isOk());
        mvc.perform(get("/api/movies/7/poster"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.message").value("影片图片不存在"));
    }

    @Test
    void missingLoginAndFileHaveExplicitClientErrors() throws Exception {
        mvc.perform(multipart("/api/movies/7/poster")
                .file(new MockMultipartFile("file", "image.png", "image/png", png)))
                .andExpect(status().isUnauthorized());
        mvc.perform(multipart("/api/movies/7/poster").header("X-Auth-Token", "admin"))
                .andExpect(status().isBadRequest());
    }

    private org.springframework.test.web.servlet.ResultActions upload(byte[] bytes) throws Exception {
        return mvc.perform(multipart("/api/movies/7/poster")
                .file(new MockMultipartFile("file", "image.png", "image/png", bytes))
                .header("X-Auth-Token", "admin"));
    }
}
