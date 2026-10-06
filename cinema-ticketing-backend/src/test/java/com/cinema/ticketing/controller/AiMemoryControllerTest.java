package com.cinema.ticketing.controller;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.GlobalExceptionHandler;
import com.cinema.ticketing.service.AiMemoryService;
import com.cinema.ticketing.service.AuthService;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class AiMemoryControllerTest {
    private final AiMemoryService memory = mock(AiMemoryService.class);
    private final AuthService auth = mock(AuthService.class);
    private MockMvc mvc;

    @BeforeEach
    void setup() {
        when(auth.requireUserId("alice")).thenReturn(1L);
        mvc =
                MockMvcBuilders.standaloneSetup(new AiMemoryController(memory, auth, "private"))
                        .setControllerAdvice(new GlobalExceptionHandler())
                        .build();
    }

    @Test
    void bodyCannotOverrideAuthenticatedOwner() throws Exception {
        mvc.perform(
                        post("/api/ai/memories")
                                .header("X-Auth-Token", "alice")
                                .contentType("application/json")
                                .content(
                                        "{\"userId\":2,\"content\":\"喜欢科幻\",\"category\":\"GENRE\"}"))
                .andExpect(status().isOk());
        verify(memory).create(eq(1L), any());
    }

    @Test
    void invalidInternalCredentialCannotReadOrClaim() throws Exception {
        mvc.perform(get("/internal/ai/memories?userId=1").header("X-Internal-Token", "wrong"))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/internal/ai/memory-index/claim").header("X-Internal-Token", "wrong"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(memory);
    }

    @Test
    void ordinaryUsersCannotReindex() throws Exception {
        doThrow(new BusinessException(403, "需要管理员权限")).when(auth).requireAdmin("alice");
        mvc.perform(post("/api/admin/ai-memory/reindex").header("X-Auth-Token", "alice"))
                .andExpect(status().isForbidden());
        verifyNoInteractions(memory);
    }
}
