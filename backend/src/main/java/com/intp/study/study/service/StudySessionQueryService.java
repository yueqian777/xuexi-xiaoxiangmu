package com.intp.study.study.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.study.dto.StudySessionDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class StudySessionQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public StudySessionQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<StudySessionDto> listForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT id, date, subject, chapter, title, main_question, mastered_content,
                       blockers, wrong_questions, summary, mastery, need_review, is_key, created_at
                FROM study_sessions
                WHERE user_id = ?
                ORDER BY date DESC, id DESC
                """, (rs, rowNum) -> new StudySessionDto(
                rs.getLong("id"),
                rs.getString("date"),
                rs.getString("subject"),
                rs.getString("chapter"),
                rs.getString("title"),
                rs.getString("main_question"),
                rs.getString("mastered_content"),
                rs.getString("blockers"),
                rs.getString("wrong_questions"),
                rs.getString("summary"),
                rs.getInt("mastery"),
                rs.getInt("need_review") != 0,
                rs.getInt("is_key") != 0,
                rs.getString("created_at")
        ), userId);
    }

    public Optional<StudySessionDto> findForCurrentUser(long id) {
        long userId = currentUserProvider.requireUserId();
        List<StudySessionDto> sessions = jdbcTemplate.query("""
                SELECT id, date, subject, chapter, title, main_question, mastered_content,
                       blockers, wrong_questions, summary, mastery, need_review, is_key, created_at
                FROM study_sessions
                WHERE user_id = ? AND id = ?
                """, (rs, rowNum) -> new StudySessionDto(
                rs.getLong("id"),
                rs.getString("date"),
                rs.getString("subject"),
                rs.getString("chapter"),
                rs.getString("title"),
                rs.getString("main_question"),
                rs.getString("mastered_content"),
                rs.getString("blockers"),
                rs.getString("wrong_questions"),
                rs.getString("summary"),
                rs.getInt("mastery"),
                rs.getInt("need_review") != 0,
                rs.getInt("is_key") != 0,
                rs.getString("created_at")
        ), userId, id);
        return sessions.stream().findFirst();
    }
}
