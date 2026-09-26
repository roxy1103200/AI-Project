package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.GlobalExceptionHandler;
import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.service.CatalogService;
import com.cinema.ticketing.service.CinemaService;
import com.cinema.ticketing.service.MoviePosterService;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class CinemaRoutingTest {

    @Test
    void cinemaPathUsesDedicatedControllerInsteadOfGenericCatalog() throws Exception {
        CinemaService cinemaService = mock(CinemaService.class);
        CatalogService catalogService = mock(CatalogService.class);
        AuthService authService = mock(AuthService.class);
        MoviePosterService posterService = mock(MoviePosterService.class);
        when(cinemaService.list()).thenReturn(List.of());
        MockMvc mvc = MockMvcBuilders.standaloneSetup(
                        new CinemaController(cinemaService, authService),
                        new CatalogController(catalogService, authService, posterService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();

        mvc.perform(get("/api/cinemas"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data").isArray());

        verify(cinemaService).list();
        verifyNoInteractions(catalogService);
    }
}
