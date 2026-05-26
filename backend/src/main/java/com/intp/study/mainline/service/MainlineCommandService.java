package com.intp.study.mainline.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.mainline.dto.BranchQuestionDto;
import com.intp.study.mainline.dto.MainlineAnchorDto;
import com.intp.study.mainline.dto.SaveBranchQuestionRequest;
import com.intp.study.mainline.dto.SaveMainlineAnchorRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.Objects;

@Service
public class MainlineCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final MainlineAnchorQueryService mainlineAnchorQueryService;

    public MainlineCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            MainlineAnchorQueryService mainlineAnchorQueryService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.mainlineAnchorQueryService = mainlineAnchorQueryService;
    }

    @Transactional
    public MainlineAnchorDto createAnchor(SaveMainlineAnchorRequest request) {
        long userId = currentUserProvider.requireUserId();
        ensureSessionExists(userId, request.sessionId());
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO mainline_anchors (user_id, session_id, anchor_code, title, content, order_index)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            ps.setLong(1, userId);
            ps.setLong(2, request.sessionId());
            ps.setString(3, request.anchorCode());
            ps.setString(4, request.title());
            ps.setString(5, defaultString(request.content()));
            ps.setInt(6, request.orderIndex());
            return ps;
        }, keyHolder);
        long id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        return mainlineAnchorQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Mainline anchor not found."));
    }

    @Transactional
    public BranchQuestionDto createBranchQuestion(SaveBranchQuestionRequest request) {
        long userId = currentUserProvider.requireUserId();
        MainlineAnchorDto anchor = mainlineAnchorQueryService.findForCurrentUser(request.anchorId())
                .orElseThrow(() -> new ResourceNotFoundException("Mainline anchor not found."));
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO branch_questions (
                        user_id, session_id, anchor_id, question, answer_summary, understood, need_review
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            ps.setLong(1, userId);
            ps.setLong(2, anchor.sessionId());
            ps.setLong(3, request.anchorId());
            ps.setString(4, request.question());
            ps.setString(5, defaultString(request.answerSummary()));
            ps.setInt(6, request.understood() ? 1 : 0);
            ps.setInt(7, request.needReview() ? 1 : 0);
            return ps;
        }, keyHolder);
        long id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        return mainlineAnchorQueryService.findBranchQuestionForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Branch question not found."));
    }

    private void ensureSessionExists(long userId, long sessionId) {
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM study_sessions
                WHERE id = ? AND user_id = ?
                """, Integer.class, sessionId, userId);
        if (count == null || count == 0) {
            throw new ResourceNotFoundException("Study session not found.");
        }
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }
}
