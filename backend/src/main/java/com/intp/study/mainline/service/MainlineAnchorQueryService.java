package com.intp.study.mainline.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.mainline.dto.MainlineAnchorDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class MainlineAnchorQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public MainlineAnchorQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<MainlineAnchorDto> listForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT ma.id, ma.session_id, ma.anchor_code, ma.title, ma.content,
                       ma.order_index, ss.date AS session_date, ss.subject AS session_subject,
                       ss.title AS session_title
                FROM mainline_anchors ma
                JOIN study_sessions ss ON ss.id = ma.session_id AND ss.user_id = ma.user_id
                WHERE ma.user_id = ?
                ORDER BY ss.date DESC, ma.order_index ASC, ma.id ASC
                """, (rs, rowNum) -> new MainlineAnchorDto(
                rs.getLong("id"),
                rs.getLong("session_id"),
                rs.getString("anchor_code"),
                rs.getString("title"),
                rs.getString("content"),
                rs.getInt("order_index"),
                rs.getString("session_date"),
                rs.getString("session_subject"),
                rs.getString("session_title")
        ), userId);
    }

    public List<MainlineAnchorDto> listForSession(long sessionId) {
        long userId = currentUserProvider.requireUserId();
        return queryAnchors("""
                SELECT ma.id, ma.session_id, ma.anchor_code, ma.title, ma.content,
                       ma.order_index, ss.date AS session_date, ss.subject AS session_subject,
                       ss.title AS session_title
                FROM mainline_anchors ma
                JOIN study_sessions ss ON ss.id = ma.session_id AND ss.user_id = ma.user_id
                WHERE ma.user_id = ? AND ma.session_id = ?
                ORDER BY ma.order_index ASC, ma.id ASC
                """, userId, sessionId);
    }

    public Optional<MainlineAnchorDto> findForCurrentUser(long anchorId) {
        long userId = currentUserProvider.requireUserId();
        return queryAnchors("""
                SELECT ma.id, ma.session_id, ma.anchor_code, ma.title, ma.content,
                       ma.order_index, ss.date AS session_date, ss.subject AS session_subject,
                       ss.title AS session_title
                FROM mainline_anchors ma
                JOIN study_sessions ss ON ss.id = ma.session_id AND ss.user_id = ma.user_id
                WHERE ma.user_id = ? AND ma.id = ?
                """, userId, anchorId).stream().findFirst();
    }

    public List<com.intp.study.mainline.dto.BranchQuestionDto> listBranchQuestionsForSession(long sessionId) {
        long userId = currentUserProvider.requireUserId();
        return queryBranchQuestions("""
                SELECT bq.id, bq.session_id, bq.anchor_id, bq.question, bq.answer_summary,
                       bq.understood, bq.need_review, bq.created_at,
                       ma.anchor_code, ma.title AS anchor_title
                FROM branch_questions bq
                JOIN mainline_anchors ma ON ma.id = bq.anchor_id AND ma.user_id = bq.user_id
                JOIN study_sessions ss ON ss.id = bq.session_id AND ss.user_id = bq.user_id
                WHERE bq.user_id = ? AND bq.session_id = ?
                ORDER BY bq.anchor_id ASC, bq.created_at ASC, bq.id ASC
                """, userId, sessionId);
    }

    public Optional<com.intp.study.mainline.dto.BranchQuestionDto> findBranchQuestionForCurrentUser(long id) {
        long userId = currentUserProvider.requireUserId();
        return queryBranchQuestions("""
                SELECT bq.id, bq.session_id, bq.anchor_id, bq.question, bq.answer_summary,
                       bq.understood, bq.need_review, bq.created_at,
                       ma.anchor_code, ma.title AS anchor_title
                FROM branch_questions bq
                JOIN mainline_anchors ma ON ma.id = bq.anchor_id AND ma.user_id = bq.user_id
                JOIN study_sessions ss ON ss.id = bq.session_id AND ss.user_id = bq.user_id
                WHERE bq.user_id = ? AND bq.id = ?
                """, userId, id).stream().findFirst();
    }

    private List<MainlineAnchorDto> queryAnchors(String sql, Object... args) {
        return jdbcTemplate.query(sql, (rs, rowNum) -> new MainlineAnchorDto(
                rs.getLong("id"),
                rs.getLong("session_id"),
                rs.getString("anchor_code"),
                rs.getString("title"),
                rs.getString("content"),
                rs.getInt("order_index"),
                rs.getString("session_date"),
                rs.getString("session_subject"),
                rs.getString("session_title")
        ), args);
    }

    private List<com.intp.study.mainline.dto.BranchQuestionDto> queryBranchQuestions(String sql, Object... args) {
        return jdbcTemplate.query(sql, (rs, rowNum) -> new com.intp.study.mainline.dto.BranchQuestionDto(
                rs.getLong("id"),
                rs.getLong("session_id"),
                rs.getLong("anchor_id"),
                rs.getString("question"),
                rs.getString("answer_summary"),
                rs.getInt("understood") != 0,
                rs.getInt("need_review") != 0,
                rs.getString("created_at"),
                rs.getString("anchor_code"),
                rs.getString("anchor_title")
        ), args);
    }
}
