package com.intp.study.mistake.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.mistake.dto.MistakeDto;
import com.intp.study.mistake.dto.SaveMistakeRequest;
import com.intp.study.review.service.ReviewScheduleService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.List;
import java.util.Objects;

@Service
public class MistakeCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final MistakeQueryService mistakeQueryService;
    private final ReviewScheduleService reviewScheduleService;

    public MistakeCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            MistakeQueryService mistakeQueryService,
            ReviewScheduleService reviewScheduleService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.mistakeQueryService = mistakeQueryService;
        this.reviewScheduleService = reviewScheduleService;
    }

    @Transactional
    public MistakeDto create(SaveMistakeRequest request) {
        long userId = currentUserProvider.requireUserId();
        ResolvedMistakeFields fields = resolveFields(userId, request);
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO mistakes (
                        user_id, subject, topic, knowledge_id, original_question,
                        my_wrong_answer, correct_idea, cause_category, warning_signal,
                        summary, add_to_review
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            bindSaveParams(ps, userId, request, fields);
            return ps;
        }, keyHolder);
        long id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        if (request.addToReview() && request.knowledgeId() != null) {
            reviewScheduleService.ensureInitialReviewTasks(userId, request.knowledgeId(), null);
        }
        return mistakeQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Mistake not found."));
    }

    @Transactional
    public MistakeDto update(long id, SaveMistakeRequest request) {
        long userId = currentUserProvider.requireUserId();
        ResolvedMistakeFields fields = resolveFields(userId, request);
        int updated = jdbcTemplate.update("""
                UPDATE mistakes
                SET subject = ?, topic = ?, knowledge_id = ?, original_question = ?,
                    my_wrong_answer = ?, correct_idea = ?, cause_category = ?,
                    warning_signal = ?, summary = ?, add_to_review = ?
                WHERE id = ? AND user_id = ?
                """,
                fields.subject(),
                fields.topic(),
                request.knowledgeId(),
                request.originalQuestion(),
                defaultString(request.myWrongAnswer()),
                request.correctIdea(),
                request.causeCategory(),
                defaultString(request.warningSignal()),
                defaultString(request.summary()),
                request.addToReview() ? 1 : 0,
                id,
                userId
        );
        if (updated == 0) {
            throw new ResourceNotFoundException("Mistake not found.");
        }
        return mistakeQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Mistake not found."));
    }

    @Transactional
    public void delete(long id) {
        long userId = currentUserProvider.requireUserId();
        int deleted = jdbcTemplate.update("""
                DELETE FROM mistakes
                WHERE id = ? AND user_id = ?
                """, id, userId);
        if (deleted == 0) {
            throw new ResourceNotFoundException("Mistake not found.");
        }
    }

    private ResolvedMistakeFields resolveFields(long userId, SaveMistakeRequest request) {
        String subject = defaultString(request.subject()).trim();
        String topic = defaultString(request.topic()).trim();
        KnowledgeCardSummary card = findKnowledgeCard(userId, request.knowledgeId());
        if (card != null) {
            if (subject.isBlank()) {
                subject = card.subject();
            }
            if (topic.isBlank()) {
                topic = card.topic();
            }
        }
        if (subject.isBlank() || topic.isBlank()) {
            throw new IllegalArgumentException("subject and topic are required when knowledgeId is not provided.");
        }
        return new ResolvedMistakeFields(subject, topic);
    }

    private KnowledgeCardSummary findKnowledgeCard(long userId, Long knowledgeId) {
        if (knowledgeId == null) {
            return null;
        }
        List<KnowledgeCardSummary> cards = jdbcTemplate.query("""
                SELECT subject, topic
                FROM knowledge_cards
                WHERE id = ? AND user_id = ?
                """, (rs, rowNum) -> new KnowledgeCardSummary(
                rs.getString("subject"),
                rs.getString("topic")
        ), knowledgeId, userId);
        if (cards.isEmpty()) {
            throw new ResourceNotFoundException("Knowledge card not found.");
        }
        return cards.getFirst();
    }

    private void bindSaveParams(
            PreparedStatement ps,
            long userId,
            SaveMistakeRequest request,
            ResolvedMistakeFields fields
    ) throws java.sql.SQLException {
        ps.setLong(1, userId);
        ps.setString(2, fields.subject());
        ps.setString(3, fields.topic());
        if (request.knowledgeId() == null) {
            ps.setNull(4, java.sql.Types.INTEGER);
        } else {
            ps.setLong(4, request.knowledgeId());
        }
        ps.setString(5, request.originalQuestion());
        ps.setString(6, defaultString(request.myWrongAnswer()));
        ps.setString(7, request.correctIdea());
        ps.setString(8, request.causeCategory());
        ps.setString(9, defaultString(request.warningSignal()));
        ps.setString(10, defaultString(request.summary()));
        ps.setInt(11, request.addToReview() ? 1 : 0);
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    private record KnowledgeCardSummary(String subject, String topic) {
    }

    private record ResolvedMistakeFields(String subject, String topic) {
    }
}
