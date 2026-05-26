package com.intp.study.knowledge.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.knowledge.dto.KnowledgeCardDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class KnowledgeCardQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public KnowledgeCardQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<KnowledgeCardDto> listForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT id, subject, topic, core_question, one_sentence, logic_or_formula,
                       application, mastery, need_review, source_session_id, created_at
                FROM knowledge_cards
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                """, (rs, rowNum) -> new KnowledgeCardDto(
                rs.getLong("id"),
                rs.getString("subject"),
                rs.getString("topic"),
                rs.getString("core_question"),
                rs.getString("one_sentence"),
                rs.getString("logic_or_formula"),
                rs.getString("application"),
                rs.getInt("mastery"),
                rs.getInt("need_review") != 0,
                rs.getObject("source_session_id", Long.class),
                rs.getString("created_at")
        ), userId);
    }

    public Optional<KnowledgeCardDto> findForCurrentUser(long id) {
        long userId = currentUserProvider.requireUserId();
        List<KnowledgeCardDto> cards = jdbcTemplate.query("""
                SELECT id, subject, topic, core_question, one_sentence, logic_or_formula,
                       application, mastery, need_review, source_session_id, created_at
                FROM knowledge_cards
                WHERE user_id = ? AND id = ?
                """, (rs, rowNum) -> new KnowledgeCardDto(
                rs.getLong("id"),
                rs.getString("subject"),
                rs.getString("topic"),
                rs.getString("core_question"),
                rs.getString("one_sentence"),
                rs.getString("logic_or_formula"),
                rs.getString("application"),
                rs.getInt("mastery"),
                rs.getInt("need_review") != 0,
                rs.getObject("source_session_id", Long.class),
                rs.getString("created_at")
        ), userId, id);
        return cards.stream().findFirst();
    }
}
