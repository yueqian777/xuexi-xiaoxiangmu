package com.intp.study.mistake.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.mistake.dto.MistakeDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class MistakeQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public MistakeQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<MistakeDto> listForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT m.id, m.subject, m.topic, m.knowledge_id, m.original_question,
                       m.my_wrong_answer, m.correct_idea, m.cause_category,
                       m.warning_signal, m.summary, m.add_to_review, m.created_at,
                       kc.topic AS knowledge_topic,
                       kc.one_sentence AS knowledge_one_sentence
                FROM mistakes m
                LEFT JOIN knowledge_cards kc
                  ON kc.id = m.knowledge_id AND kc.user_id = m.user_id
                WHERE m.user_id = ?
                ORDER BY m.created_at DESC, m.id DESC
                """, (rs, rowNum) -> new MistakeDto(
                rs.getLong("id"),
                rs.getString("subject"),
                rs.getString("topic"),
                rs.getObject("knowledge_id", Long.class),
                rs.getString("original_question"),
                rs.getString("my_wrong_answer"),
                rs.getString("correct_idea"),
                rs.getString("cause_category"),
                rs.getString("warning_signal"),
                rs.getString("summary"),
                rs.getInt("add_to_review") != 0,
                rs.getString("created_at"),
                rs.getString("knowledge_topic"),
                rs.getString("knowledge_one_sentence")
        ), userId);
    }
}
