package com.intp.study.knowledge.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.knowledge.dto.KnowledgeCardDto;
import com.intp.study.knowledge.dto.SaveKnowledgeCardRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.Objects;

@Service
public class KnowledgeCardCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final KnowledgeCardQueryService knowledgeCardQueryService;

    public KnowledgeCardCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            KnowledgeCardQueryService knowledgeCardQueryService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.knowledgeCardQueryService = knowledgeCardQueryService;
    }

    @Transactional
    public KnowledgeCardDto create(SaveKnowledgeCardRequest request) {
        long userId = currentUserProvider.requireUserId();
        validateSourceSession(userId, request.sourceSessionId());
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO knowledge_cards (
                        user_id, subject, topic, core_question, one_sentence,
                        logic_or_formula, application, mastery, need_review, source_session_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            bindSaveParams(ps, userId, request);
            return ps;
        }, keyHolder);
        long id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        return knowledgeCardQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Knowledge card not found."));
    }

    @Transactional
    public KnowledgeCardDto update(long id, SaveKnowledgeCardRequest request) {
        long userId = currentUserProvider.requireUserId();
        validateSourceSession(userId, request.sourceSessionId());
        int updated = jdbcTemplate.update("""
                UPDATE knowledge_cards
                SET subject = ?, topic = ?, core_question = ?, one_sentence = ?,
                    logic_or_formula = ?, application = ?, mastery = ?,
                    need_review = ?, source_session_id = ?
                WHERE id = ? AND user_id = ?
                """,
                request.subject(),
                request.topic(),
                defaultString(request.coreQuestion()),
                request.oneSentence(),
                defaultString(request.logicOrFormula()),
                defaultString(request.application()),
                request.mastery(),
                request.needReview() ? 1 : 0,
                request.sourceSessionId(),
                id,
                userId
        );
        if (updated == 0) {
            throw new ResourceNotFoundException("Knowledge card not found.");
        }
        return knowledgeCardQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Knowledge card not found."));
    }

    @Transactional
    public void delete(long id) {
        long userId = currentUserProvider.requireUserId();
        int deleted = jdbcTemplate.update("""
                DELETE FROM knowledge_cards
                WHERE id = ? AND user_id = ?
                """, id, userId);
        if (deleted == 0) {
            throw new ResourceNotFoundException("Knowledge card not found.");
        }
    }

    private void validateSourceSession(long userId, Long sourceSessionId) {
        if (sourceSessionId == null) {
            return;
        }
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM study_sessions
                WHERE id = ? AND user_id = ?
                """, Integer.class, sourceSessionId, userId);
        if (count == null || count == 0) {
            throw new ResourceNotFoundException("Source study session not found.");
        }
    }

    private void bindSaveParams(PreparedStatement ps, long userId, SaveKnowledgeCardRequest request) throws java.sql.SQLException {
        ps.setLong(1, userId);
        ps.setString(2, request.subject());
        ps.setString(3, request.topic());
        ps.setString(4, defaultString(request.coreQuestion()));
        ps.setString(5, request.oneSentence());
        ps.setString(6, defaultString(request.logicOrFormula()));
        ps.setString(7, defaultString(request.application()));
        ps.setInt(8, request.mastery());
        ps.setInt(9, request.needReview() ? 1 : 0);
        if (request.sourceSessionId() == null) {
            ps.setNull(10, java.sql.Types.INTEGER);
        } else {
            ps.setLong(10, request.sourceSessionId());
        }
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }
}
