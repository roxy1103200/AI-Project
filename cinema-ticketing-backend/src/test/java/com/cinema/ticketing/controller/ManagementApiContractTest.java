package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.GlobalExceptionHandler;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.CatalogService;
import com.cinema.ticketing.service.MoviePosterService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ManagementApiContractTest {
    private final CatalogService catalog = mock(CatalogService.class);
    private final AuthService auth = mock(AuthService.class);
    private MockMvc mvc;

    @BeforeEach
    void setup() {
        doThrow(new BusinessException(401, "请登录")).when(auth).requireAdmin(isNull());
        mvc = MockMvcBuilders.standaloneSetup(
                        new CatalogController(catalog, auth, mock(MoviePosterService.class)),
                        new SystemController())
                .setControllerAdvice(new GlobalExceptionHandler()).build();
    }

    @Test
    void publicRequestsCannotReadUserAccounts() throws Exception {
        mvc.perform(get("/api/users")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/users/7")).andExpect(status().isUnauthorized());
        verifyNoInteractions(catalog);
    }

    @Test
    void invalidIdIsAClientError() throws Exception {
        mvc.perform(get("/api/movies/not-a-number"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void missingLoginDoesNotBecomeServerError() throws Exception {
        mvc.perform(post("/api/movies").contentType("application/json").content("{}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void healthAdvertisesPosterSupportForEditorPreflight() throws Exception {
        mvc.perform(get("/api/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.features.moviePosters").value(true));
    }

    @Test
    void wrongMethodAndContentTypeDoNotBecomeServerErrors() throws Exception {
        mvc.perform(patch("/api/health")).andExpect(status().isMethodNotAllowed());
        mvc.perform(post("/api/movies").contentType("text/plain").content("{}"))
                .andExpect(status().isUnsupportedMediaType());
    }
}
