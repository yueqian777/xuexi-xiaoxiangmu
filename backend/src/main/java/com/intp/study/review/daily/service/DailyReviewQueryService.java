package com.intp.study.review.daily.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.review.daily.dto.DailyAiReviewPlanDto;
import com.intp.study.review.daily.dto.DailyReviewLogDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

@Service
public class DailyReviewQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public DailyReviewQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<DailyReviewLogDto> listLogsForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT id, review_date, status, notes, created_at
                FROM daily_review_logs
                WHERE user_id = ?
                ORDER BY review_date DESC, id DESC
                """, (rs, rowNum) -> new DailyReviewLogDto(
                rs.getLong("id"),
                rs.getString("review_date"),
                rs.getString("status"),
                rs.getString("notes"),
                rs.getString("created_at")
        ), userId);
    }

    public List<DailyAiReviewPlanDto> listAiPlansForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return queryPlans("""
                SELECT id, review_date, provider_key, model, plan_json, source_snapshot_json,
                       answers_json, evaluation_json, status, created_at, evaluated_at
                FROM daily_ai_review_plans
                WHERE user_id = ?
                ORDER BY review_date DESC, id DESC
                """, userId);
    }

    public Optional<DailyAiReviewPlanDto> findTodayAiPlanForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return queryPlans("""
                SELECT id, review_date, provider_key, model, plan_json, source_snapshot_json,
                       answers_json, evaluation_json, status, created_at, evaluated_at
                FROM daily_ai_review_plans
                WHERE user_id = ? AND review_date = ?
                """, userId, LocalDate.now().toString()).stream().findFirst();
    }

    private List<DailyAiReviewPlanDto> queryPlans(String sql, Object... args) {
        return jdbcTemplate.query(sql, (rs, rowNum) -> new DailyAiReviewPlanDto(
                rs.getLong("id"),
                rs.getString("review_date"),
                rs.getString("provider_key"),
                rs.getString("model"),
                rs.getString("plan_json"),
                rs.getString("source_snapshot_json"),
                rs.getString("answers_json"),
                rs.getString("evaluation_json"),
                rs.getString("status"),
                rs.getString("created_at"),
                rs.getString("evaluated_at")
        ), args);
    }
}
