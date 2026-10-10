package com.cinema.ticketing.controller;

import com.cinema.ticketing.service.AuthService;
import com.cinema.ticketing.common.BusinessException;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class RefundPolicyConsistencyTest {
    @Test
    void internalAndAdminReadsAgreeWithNumericRuleOnLegacyData() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForMap(contains("content policy"))).thenReturn(Map.of(
                "version", "legacy", "policy", "开场前30分钟退票", "cutoff_minutes", 5));
        when(jdbc.queryForList(contains("FROM refund_policy"))).thenReturn(List.of(Map.of(
                "policy_version", "legacy", "content", "开场前30分钟退票", "cutoff_minutes", 5)));
        var internal = new InternalAiController(jdbc, "token").refundPolicy("token");
        var admin = new RefundPolicyController(jdbc, mock(AuthService.class)).current("admin").data();
        assertEquals(internal.get("policy"), admin.get("content"));
        assertFalse(internal.get("policy").toString().contains("30"));
        assertEquals(5, internal.get("cutoff_minutes"));
    }

    @Test
    void publishingRewritesDeadlineWithoutChangingNumericParameter() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        new RefundPolicyController(jdbc, mock(AuthService.class)).update("admin",
                new RefundPolicyController.PolicyInput(5, "开场前30分钟截止，已出票才可申请"));
        verify(jdbc).update(contains("INSERT INTO refund_policy"), anyString(), eq(5),
                argThat((String text) -> text.contains("开场前 5 分钟") && !text.contains("30")));
    }

    @Test
    void generatedHeaderDoesNotConsumeTheStoredDescriptionLimit() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        String description = "补充说明".repeat(250);
        new RefundPolicyController(jdbc, mock(AuthService.class)).update("admin",
                new RefundPolicyController.PolicyInput(5, description));
        verify(jdbc).update(contains("INSERT INTO refund_policy"), anyString(), eq(5), eq(description));
    }

    @Test
    void normalizedOverflowIsRejectedBeforeChangingTheActivePolicy() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        var controller = new RefundPolicyController(jdbc, mock(AuthService.class));
        BusinessException error = assertThrows(BusinessException.class, () -> controller.update("admin",
                new RefundPolicyController.PolicyInput(5, "开场前1分钟" + "字".repeat(994))));
        assertEquals(400, error.getCode());
        verifyNoInteractions(jdbc);
    }
}
