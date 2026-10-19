package com.cinema.ticketing.controller;

import com.cinema.ticketing.common.BusinessException;
import com.cinema.ticketing.common.GlobalExceptionHandler;
import com.cinema.ticketing.service.AdminOrderQueryService;
import com.cinema.ticketing.service.AuthService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AdminOrderQueryControllerTest {
    private AuthService auth;
    private AdminOrderQueryService query;
    private MockMvc mvc;

    @BeforeEach void setup() {
        auth = mock(AuthService.class); query = mock(AdminOrderQueryService.class);
        mvc = MockMvcBuilders.standaloneSetup(new AdminOrderQueryController(query, auth))
                .setControllerAdvice(new GlobalExceptionHandler()).build();
    }

    @Test void missingLoginCannotReadAnOrder() throws Exception {
        mvc.perform(get("/api/admin/orders/ORDER-A9EC9EE9"))
                .andExpect(status().isUnauthorized()).andExpect(header().string("Cache-Control", "no-store"));
        verifyNoInteractions(query);
    }

    @Test void normalUserCannotLookUpAnotherUserEvenWithCorrectNumber() throws Exception {
        doThrow(new BusinessException(403,"需要管理员权限")).when(auth).requireAdmin("user");
        mvc.perform(get("/api/admin/orders/ORDER-A9EC9EE9").header("X-Auth-Token","user"))
                .andExpect(status().isForbidden());
        verifyNoInteractions(query);
    }

    @Test void revokedOrDowngradedSessionIsCheckedBeforeLookup() throws Exception {
        doThrow(new BusinessException(401,"登录已失效")).when(auth).requireAdmin("revoked");
        doThrow(new BusinessException(403,"需要管理员权限")).when(auth).requireAdmin("downgraded");
        mvc.perform(get("/api/admin/orders/ORDER-A9EC9EE9").header("X-Auth-Token","revoked")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/admin/orders/ORDER-A9EC9EE9").header("X-Auth-Token","downgraded")).andExpect(status().isForbidden());
        verifyNoInteractions(query);
    }

    @Test void administratorUsesDedicatedQueryAndResponseIsNeverCached() throws Exception {
        mvc.perform(get("/api/admin/orders/ORDER-A9EC9EE9").header("X-Auth-Token","admin"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(header().string("Cache-Control","no-store"));
        var sequence = inOrder(auth, query);
        sequence.verify(auth).requireAdmin("admin");
        sequence.verify(query).find("ORDER-A9EC9EE9");
    }

    @Test void missingOrderAndDatabaseFailureHaveDifferentResponses() throws Exception {
        when(query.find("missing")).thenThrow(new BusinessException(404,"未找到该订单"));
        when(query.find("broken")).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("offline"));
        mvc.perform(get("/api/admin/orders/missing").header("X-Auth-Token","admin")).andExpect(status().isNotFound());
        mvc.perform(get("/api/admin/orders/broken").header("X-Auth-Token","admin"))
                .andExpect(status().isInternalServerError()).andExpect(jsonPath("$.message").value("服务器内部错误"));
    }

    @Test void detailEndpointDoesNotAcceptMutation() throws Exception {
        mvc.perform(post("/api/admin/orders/ORDER-A9EC9EE9").header("X-Auth-Token","admin")).andExpect(status().isMethodNotAllowed());
        verifyNoInteractions(query);
    }
}
