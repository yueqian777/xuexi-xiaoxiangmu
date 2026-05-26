package com.intp.study.review.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.review.dto.ReviewTaskDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ReviewTaskQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public ReviewTaskQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<ReviewTaskDto> listForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return query("""
                SELECT rt.id, rt.knowledge_id, rt.review_date, rt.review_stage, rt.status,
                       rt.result, rt.created_at, kc.subject, kc.topic, kc.core_question,
                       kc.one_sentence, kc.mastery
                FROM review_tasks rt
                JOIN knowledge_cards kc ON kc.id = rt.knowledge_id
                WHERE rt.user_id = ? AND kc.user_id = ?
                ORDER BY rt.review_date ASC, rt.id ASC
                """, userId);
    }

    public List<ReviewTaskDto> listDueForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return query("""
                SELECT rt.id, rt.knowledge_id, rt.review_date, rt.review_stage, rt.status,
                       rt.result, rt.created_at, kc.subject, kc.topic, kc.core_question,
                       kc.one_sentence, kc.mastery
                FROM review_tasks rt
                JOIN knowledge_cards kc ON kc.id = rt.knowledge_id
                WHERE rt.user_id = ? AND kc.user_id = ?
                  AND rt.status = '待复习'
                  AND rt.review_date <= date('now', 'localtime')
                ORDER BY rt.review_date ASC, rt.id ASC
                """, userId);
    }

    private List<ReviewTaskDto> query(String sql, long userId) {
        return jdbcTemplate.query(sql, (rs, rowNum) -> new ReviewTaskDto(
                rs.getLong("id"),
                rs.getLong("knowledge_id"),
                rs.getString("review_date"),
                rs.getString("review_stage"),
                rs.getString("status"),
                rs.getString("result"),
                rs.getString("created_at"),
                rs.getString("subject"),
                rs.getString("topic"),
                rs.getString("core_question"),
                rs.getString("one_sentence"),
                rs.getInt("mastery")
        ), userId, userId);
    }
}
