package com.intp.study.review.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.List;

@Service
public class ReviewScheduleService {
    private static final List<ReviewInterval> REVIEW_INTERVALS = List.of(
            new ReviewInterval(1, "第 1 天复习"),
            new ReviewInterval(3, "第 3 天复习"),
            new ReviewInterval(7, "第 7 天复习"),
            new ReviewInterval(14, "第 14 天复习")
    );

    private final JdbcTemplate jdbcTemplate;

    public ReviewScheduleService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void createInitialReviewTasks(long userId, long knowledgeId, String startDate) {
        LocalDate baseDate = parseDateOrToday(startDate);
        for (ReviewInterval interval : REVIEW_INTERVALS) {
            jdbcTemplate.update("""
                    INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
                    VALUES (?, ?, ?, ?)
                    """,
                    userId,
                    knowledgeId,
                    baseDate.plusDays(interval.days()).toString(),
                    interval.stage()
            );
        }
    }

    public void ensureInitialReviewTasks(long userId, long knowledgeId, String startDate) {
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM review_tasks
                WHERE user_id = ? AND knowledge_id = ?
                """, Integer.class, userId, knowledgeId);
        if (count == null || count == 0) {
            createInitialReviewTasks(userId, knowledgeId, startDate);
        }
    }

    private LocalDate parseDateOrToday(String value) {
        if (value == null || value.isBlank()) {
            return LocalDate.now();
        }
        try {
            return LocalDate.parse(value.substring(0, Math.min(10, value.length())));
        } catch (DateTimeParseException ex) {
            return LocalDate.now();
        }
    }

    private record ReviewInterval(int days, String stage) {
    }
}
