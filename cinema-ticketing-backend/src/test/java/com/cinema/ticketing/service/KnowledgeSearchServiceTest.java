package com.cinema.ticketing.service;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class KnowledgeSearchServiceTest {
    @Test
    void realSqlRecallsNaturalQuestionAndExcludesUnpublishedDocuments() {
        JdbcTemplate jdbc = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:recall;DB_CLOSE_DELAY=-1"));
        jdbc.execute("CREATE TABLE knowledge_document(id BIGINT, title VARCHAR(200), content VARCHAR(1000), "
                + "document_type VARCHAR(50), version VARCHAR(30), status VARCHAR(30))");
        jdbc.update("INSERT INTO knowledge_document VALUES(1,'退票规则','已出票订单可申请退票','REFUND','v1','PUBLISHED')");
        jdbc.update("INSERT INTO knowledge_document VALUES(2,'退票草稿','提前三十分钟','REFUND','v2','DRAFT')");
        var rows = new KnowledgeSearchService(jdbc).search("请解释当前退票规则，提前多少分钟截止？");
        assertEquals(1, rows.size());
        assertEquals(1L, rows.getFirst().get("id"));
    }

    @Test
    void naturalQuestionsRecallTopicsAndSynonyms() {
        assertTrue(KnowledgeSearchService.terms("请解释当前退票规则，提前多少分钟截止？").contains("退票"));
        assertTrue(KnowledgeSearchService.terms("买票超时没付款怎么办？").containsAll(List.of("购票", "超时", "支付")));
        assertFalse(KnowledgeSearchService.terms("退款需要什么条件？").contains("退款"));
    }

    @Test
    void candidatesAreBoundedAndTitleMatchesRankFirst() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(
                Map.of("id", 2, "title", "购票说明", "content", "可咨询退票"),
                Map.of("id", 1, "title", "退票规则", "content", "开场前可申请")));
        var result = new KnowledgeSearchService(jdbc).search("请问退票怎么操作？");
        assertEquals(1, result.getFirst().get("id"));
        verify(jdbc).queryForList(contains("status='PUBLISHED'"), any(Object[].class));
    }

    @Test
    void emptyOrPunctuationQueryNeverLoadsAllDocuments() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        assertTrue(new KnowledgeSearchService(jdbc).search(" % ' _ ").isEmpty());
        verifyNoInteractions(jdbc);
    }
}
