package com.intp.study.dashboard.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.dashboard.dto.DashboardCountsDto;
import com.intp.study.dashboard.dto.DashboardSummaryDto;
import com.intp.study.dashboard.dto.LowMasteryCardDto;
import com.intp.study.dashboard.dto.OpenParkingQuestionDto;
import com.intp.study.dashboard.dto.RecentBlockerDto;
import com.intp.study.dashboard.dto.RecentKnowledgeLinkDto;
import com.intp.study.reminder.dto.DailyReminderStatusDto;
import com.intp.study.reminder.service.DailyReminderService;
import com.intp.study.review.dto.ReviewTaskDto;
import com.intp.study.review.service.ReviewTaskQueryService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;

@Service
public class DashboardQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final ReviewTaskQueryService reviewTaskQueryService;
    private final DailyReminderService dailyReminderService;

    public DashboardQueryService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            ReviewTaskQueryService reviewTaskQueryService,
            DailyReminderService dailyReminderService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.reviewTaskQueryService = reviewTaskQueryService;
        this.dailyReminderService = dailyReminderService;
    }

    public DashboardSummaryDto summary() {
        long userId = currentUserProvider.requireUserId();
        List<ReviewTaskDto> dueTasks = reviewTaskQueryService.listDueForCurrentUser();
        List<LowMasteryCardDto> lowCards = lowMasteryCards(userId, 10);
        List<RecentBlockerDto> blockers = recentBlockers(userId, 8);
        List<OpenParkingQuestionDto> parking = openParkingQuestions(userId, 10);
        List<RecentKnowledgeLinkDto> links = recentKnowledgeLinks(userId, 8);
        DailyReminderStatusDto reminder = dailyReminderService.getStatus();
        return new DashboardSummaryDto(
                LocalDate.now().toString(),
                new DashboardCountsDto(dueTasks.size(), lowCards.size(), blockers.size(), parking.size(), links.size()),
                reminder,
                dueTasks,
                lowCards,
                blockers,
                parking,
                links
        );
    }

    private List<LowMasteryCardDto> lowMasteryCards(long userId, int limit) {
        return jdbcTemplate.query("""
                SELECT id, subject, topic, mastery, core_question
                FROM knowledge_cards
                WHERE user_id = ? AND mastery < 70
                ORDER BY mastery ASC, created_at DESC
                LIMIT ?
                """, (rs, rowNum) -> new LowMasteryCardDto(
                rs.getLong("id"),
                rs.getString("subject"),
                rs.getString("topic"),
                rs.getInt("mastery"),
                rs.getString("core_question")
        ), userId, limit);
    }

    private List<RecentBlockerDto> recentBlockers(long userId, int limit) {
        return jdbcTemplate.query("""
                SELECT id, date, subject, title, blockers, mastery
                FROM study_sessions
                WHERE user_id = ? AND TRIM(blockers) != ''
                ORDER BY date DESC, id DESC
                LIMIT ?
                """, (rs, rowNum) -> new RecentBlockerDto(
                rs.getLong("id"),
                rs.getString("date"),
                rs.getString("subject"),
                rs.getString("title"),
                rs.getString("blockers"),
                rs.getInt("mastery")
        ), userId, limit);
    }

    private List<OpenParkingQuestionDto> openParkingQuestions(long userId, int limit) {
        return jdbcTemplate.query("""
                SELECT id, subject, question, source, status, created_at
                FROM parking_lot
                WHERE user_id = ? AND status != '已解决'
                ORDER BY created_at DESC
                LIMIT ?
                """, (rs, rowNum) -> new OpenParkingQuestionDto(
                rs.getLong("id"),
                rs.getString("subject"),
                rs.getString("question"),
                rs.getString("source"),
                rs.getString("status"),
                rs.getString("created_at")
        ), userId, limit);
    }

    private List<RecentKnowledgeLinkDto> recentKnowledgeLinks(long userId, int limit) {
        return jdbcTemplate.query("""
                SELECT
                    kl.relation_type,
                    kl.relation_note,
                    kl.compare_points,
                    kl.created_at,
                    source.subject AS source_subject,
                    source.topic AS source_topic,
                    target.subject AS target_subject,
                    target.topic AS target_topic
                FROM knowledge_links kl
                JOIN knowledge_cards source ON source.id = kl.source_knowledge_id AND source.user_id = kl.user_id
                JOIN knowledge_cards target ON target.id = kl.target_knowledge_id AND target.user_id = kl.user_id
                WHERE kl.user_id = ?
                ORDER BY kl.created_at DESC, kl.id DESC
                LIMIT ?
                """, (rs, rowNum) -> new RecentKnowledgeLinkDto(
                rs.getString("relation_type"),
                rs.getString("relation_note"),
                rs.getString("compare_points"),
                rs.getString("created_at"),
                rs.getString("source_subject"),
                rs.getString("source_topic"),
                rs.getString("target_subject"),
                rs.getString("target_topic")
        ), userId, limit);
    }
}
