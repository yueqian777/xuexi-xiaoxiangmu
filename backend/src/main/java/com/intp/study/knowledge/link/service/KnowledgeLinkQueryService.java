package com.intp.study.knowledge.link.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.knowledge.link.dto.KnowledgeLinkDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class KnowledgeLinkQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public KnowledgeLinkQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<KnowledgeLinkDto> listForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return query("""
                SELECT kl.id, kl.source_knowledge_id, kl.target_knowledge_id,
                       kl.relation_type, kl.relation_note, kl.compare_points, kl.created_at,
                       source.topic AS source_topic,
                       source.one_sentence AS source_one_sentence,
                       target.topic AS target_topic,
                       target.one_sentence AS target_one_sentence
                FROM knowledge_links kl
                JOIN knowledge_cards source
                  ON source.id = kl.source_knowledge_id AND source.user_id = kl.user_id
                JOIN knowledge_cards target
                  ON target.id = kl.target_knowledge_id AND target.user_id = kl.user_id
                WHERE kl.user_id = ?
                ORDER BY kl.created_at DESC, kl.id DESC
                """, userId);
    }

    public List<KnowledgeLinkDto> listForCard(long cardId) {
        long userId = currentUserProvider.requireUserId();
        return query("""
                SELECT kl.id, kl.source_knowledge_id, kl.target_knowledge_id,
                       kl.relation_type, kl.relation_note, kl.compare_points, kl.created_at,
                       source.topic AS source_topic,
                       source.one_sentence AS source_one_sentence,
                       target.topic AS target_topic,
                       target.one_sentence AS target_one_sentence
                FROM knowledge_links kl
                JOIN knowledge_cards source
                  ON source.id = kl.source_knowledge_id AND source.user_id = kl.user_id
                JOIN knowledge_cards target
                  ON target.id = kl.target_knowledge_id AND target.user_id = kl.user_id
                WHERE kl.user_id = ?
                  AND (kl.source_knowledge_id = ? OR kl.target_knowledge_id = ?)
                ORDER BY kl.created_at DESC, kl.id DESC
                """, userId, cardId, cardId);
    }

    private List<KnowledgeLinkDto> query(String sql, Object... args) {
        return jdbcTemplate.query(sql, (rs, rowNum) -> new KnowledgeLinkDto(
                rs.getLong("id"),
                rs.getLong("source_knowledge_id"),
                rs.getLong("target_knowledge_id"),
                rs.getString("relation_type"),
                rs.getString("relation_note"),
                rs.getString("compare_points"),
                rs.getString("created_at"),
                rs.getString("source_topic"),
                rs.getString("source_one_sentence"),
                rs.getString("target_topic"),
                rs.getString("target_one_sentence")
        ), args);
    }
}
