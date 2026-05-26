package com.intp.study.review.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.review.dto.MarkReviewResultRequest;
import com.intp.study.review.dto.ReviewTaskDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.List;

@Service
public class ReviewTaskCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final ReviewTaskQueryService reviewTaskQueryService;

    public ReviewTaskCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            ReviewTaskQueryService reviewTaskQueryService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.reviewTaskQueryService = reviewTaskQueryService;
    }

    @Transactional
    public ReviewTaskDto markResult(long taskId, MarkReviewResultRequest request) {
        long userId = currentUserProvider.requireUserId();
        ReviewTaskSnapshot task = findTask(userId, taskId);
        int newMastery = applyReviewResult(task.mastery(), request.result());
        jdbcTemplate.update("""
                UPDATE review_tasks
                SET status = '已完成', result = ?
                WHERE id = ? AND user_id = ?
                """, request.result(), taskId, userId);
        jdbcTemplate.update("""
                UPDATE knowledge_cards
                SET mastery = ?
                WHERE id = ? AND user_id = ?
                """, newMastery, task.knowledgeId(), userId);

        if ("仍然模糊".equals(request.result())) {
            createExtraReview(userId, task.knowledgeId(), 2, "追加复习：2 天后");
        } else if ("完全不会".equals(request.result())) {
            createExtraReview(userId, task.knowledgeId(), 1, "重点突破：1 天后");
        }

        return reviewTaskQueryService.findForCurrentUser(taskId)
                .orElseThrow(() -> new ResourceNotFoundException("Review task not found."));
    }

    private ReviewTaskSnapshot findTask(long userId, long taskId) {
        List<ReviewTaskSnapshot> tasks = jdbcTemplate.query("""
                SELECT rt.knowledge_id, kc.mastery
                FROM review_tasks rt
                JOIN knowledge_cards kc ON kc.id = rt.knowledge_id AND kc.user_id = rt.user_id
                WHERE rt.id = ? AND rt.user_id = ?
                """, (rs, rowNum) -> new ReviewTaskSnapshot(
                rs.getLong("knowledge_id"),
                rs.getInt("mastery")
        ), taskId, userId);
        if (tasks.isEmpty()) {
            throw new ResourceNotFoundException("Review task not found.");
        }
        return tasks.getFirst();
    }

    private int applyReviewResult(int currentMastery, String result) {
        int delta = switch (result) {
            case "完全掌握" -> 15;
            case "基本掌握" -> 5;
            case "仍然模糊" -> -5;
            case "完全不会" -> -15;
            default -> 0;
        };
        return Math.max(0, Math.min(100, currentMastery + delta));
    }

    private void createExtraReview(long userId, long knowledgeId, int days, String stage) {
        jdbcTemplate.update("""
                INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
                VALUES (?, ?, ?, ?)
                """, userId, knowledgeId, LocalDate.now().plusDays(days).toString(), stage);
    }

    private record ReviewTaskSnapshot(long knowledgeId, int mastery) {
    }
}
