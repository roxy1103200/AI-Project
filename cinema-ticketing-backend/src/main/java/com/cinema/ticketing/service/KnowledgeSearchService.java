package com.cinema.ticketing.service;

import org.springframework.jdbc.core.JdbcTemplate;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/** Bounded lexical recall before the Agent's semantic reranker. */
public final class KnowledgeSearchService {
    private static final Pattern WORDS = Pattern.compile("[a-z0-9]+|[\\p{IsHan}]{2,}");
    private static final List<String> TOPICS = List.of(
            "退票", "购票", "支付", "出票", "订单", "座位", "锁座", "超时", "会员", "优惠", "儿童票", "发票");
    private final JdbcTemplate jdbc;

    public KnowledgeSearchService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public static List<String> terms(String query) {
        String text = query.toLowerCase(Locale.ROOT).replace("退钱", "退票").replace("退款", "退票")
                .replace("买票", "购票").replace("付款", "支付").replace("选座", "座位");
        LinkedHashSet<String> terms = new LinkedHashSet<>();
        for (String topic : TOPICS) if (text.contains(topic)) terms.add(topic);
        String stripped = text.replaceAll("请问|请|解释|当前|需要|满足|什么|哪些|怎么|如何|可以|是否|多少|相关|的|了|吗|呢", " ");
        var matcher = WORDS.matcher(stripped);
        while (matcher.find() && terms.size() < 16) {
            String word = matcher.group();
            if (word.length() <= 12) terms.add(word);
            if (word.matches("[\\p{IsHan}]+")) {
                for (int i = 0; i + 2 <= word.length() && terms.size() < 16; i++) terms.add(word.substring(i, i + 2));
            }
        }
        return terms.stream().limit(16).toList();
    }

    public List<Map<String, Object>> search(String query) {
        if (query == null || query.isBlank()) return List.of();
        List<String> terms = terms(query.substring(0, Math.min(query.length(), 500)));
        if (terms.isEmpty()) return List.of();
        List<Object> parameters = new ArrayList<>();
        List<String> clauses = new ArrayList<>();
        for (String term : terms) {
            clauses.add("(title LIKE ? OR content LIKE ?)");
            // Terms contain only letters/digits/Han; no user-controlled LIKE wildcards or SQL.
            parameters.add("%" + term.replace("_", "") + "%");
            parameters.add(parameters.getLast());
        }
        var rows = jdbc.queryForList("SELECT id,title,content,document_type,version FROM knowledge_document "
                + "WHERE status='PUBLISHED' AND (" + String.join(" OR ", clauses) + ") ORDER BY id DESC LIMIT 60",
                parameters.toArray());
        return rows.stream().sorted(Comparator.<Map<String, Object>>comparingInt(row -> score(row, terms))
                .reversed()).limit(20).toList();
    }

    private static int score(Map<String, Object> row, List<String> terms) {
        String title = String.valueOf(row.get("title")).toLowerCase(Locale.ROOT);
        String content = String.valueOf(row.get("content")).toLowerCase(Locale.ROOT);
        return terms.stream().mapToInt(term -> (title.contains(term) ? 4 : 0) + (content.contains(term) ? 1 : 0)).sum();
    }
}
