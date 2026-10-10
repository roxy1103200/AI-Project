package com.cinema.ticketing.common;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class RefundPolicyTextTest {
    @Test
    void numericRuleReplacesLegacyDeadlineAndPreservesOtherConditions() {
        String content = RefundPolicyText.render(5, "仅支持开场前 30 分钟完成退票，已出票订单可申请退票。");
        assertFalse(content.contains("30"));
        assertTrue(content.contains("开场前 5 分钟"));
        assertTrue(content.contains("已出票订单"));
        assertTrue(content.contains("到达截止时间及之后不能退票"));
    }

    @Test
    void renderingIsIdempotentAndChangesBothGeneratedAndLegacyWording() {
        String content = RefundPolicyText.render(5, "请提前三十分钟退票，手续费为 2 元。");
        assertEquals(content, RefundPolicyText.render(5, content));
        String updated = RefundPolicyText.render(0, content);
        assertFalse(updated.contains("5 分钟"));
        assertTrue(updated.contains("提前 0 分钟"));
        assertTrue(updated.contains("手续费为 2 元"));
    }

    @Test
    void normalizeDoesNotMutateStoredRowOrVersion() {
        var row = Map.<String, Object>of("cutoff_minutes", 5, "policy", "开场前半小时退票", "version", "v1");
        var result = RefundPolicyText.normalize(row, "policy");
        assertEquals("v1", result.get("version"));
        assertEquals("开场前半小时退票", row.get("policy"));
        assertFalse(result.get("policy").toString().contains("半小时"));
    }
}
