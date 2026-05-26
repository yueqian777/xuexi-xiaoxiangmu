package com.intp.study.study.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.study.dto.SaveStudySessionRequest;
import com.intp.study.study.dto.StudySessionDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.Objects;

@Service
public class StudySessionCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final StudySessionQueryService studySessionQueryService;

    public StudySessionCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            StudySessionQueryService studySessionQueryService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.studySessionQueryService = studySessionQueryService;
    }

    @Transactional
    public StudySessionDto create(SaveStudySessionRequest request) {
        long userId = currentUserProvider.requireUserId();
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO study_sessions (
                        user_id, date, subject, chapter, title, main_question,
                        mastered_content, blockers, wrong_questions, summary,
                        mastery, need_review, is_key
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            bindSaveParams(ps, userId, request);
            return ps;
        }, keyHolder);
        long id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        return studySessionQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Study session not found."));
    }

    @Transactional
    public StudySessionDto update(long id, SaveStudySessionRequest request) {
        long userId = currentUserProvider.requireUserId();
        int updated = jdbcTemplate.update("""
                UPDATE study_sessions
                SET date = ?, subject = ?, chapter = ?, title = ?, main_question = ?,
                    mastered_content = ?, blockers = ?, wrong_questions = ?, summary = ?,
                    mastery = ?, need_review = ?, is_key = ?
                WHERE id = ? AND user_id = ?
                """,
                request.date(),
                request.subject(),
                defaultString(request.chapter()),
                request.title(),
                request.mainQuestion(),
                defaultString(request.masteredContent()),
                defaultString(request.blockers()),
                defaultString(request.wrongQuestions()),
                defaultString(request.summary()),
                request.mastery(),
                request.needReview() ? 1 : 0,
                request.key() ? 1 : 0,
                id,
                userId
        );
        if (updated == 0) {
            throw new ResourceNotFoundException("Study session not found.");
        }
        return studySessionQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Study session not found."));
    }

    @Transactional
    public void delete(long id) {
        long userId = currentUserProvider.requireUserId();
        int deleted = jdbcTemplate.update("""
                DELETE FROM study_sessions
                WHERE id = ? AND user_id = ?
                """, id, userId);
        if (deleted == 0) {
            throw new ResourceNotFoundException("Study session not found.");
        }
    }

    private void bindSaveParams(PreparedStatement ps, long userId, SaveStudySessionRequest request) throws java.sql.SQLException {
        ps.setLong(1, userId);
        ps.setString(2, request.date());
        ps.setString(3, request.subject());
        ps.setString(4, defaultString(request.chapter()));
        ps.setString(5, request.title());
        ps.setString(6, request.mainQuestion());
        ps.setString(7, defaultString(request.masteredContent()));
        ps.setString(8, defaultString(request.blockers()));
        ps.setString(9, defaultString(request.wrongQuestions()));
        ps.setString(10, defaultString(request.summary()));
        ps.setInt(11, request.mastery());
        ps.setInt(12, request.needReview() ? 1 : 0);
        ps.setInt(13, request.key() ? 1 : 0);
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }
}
