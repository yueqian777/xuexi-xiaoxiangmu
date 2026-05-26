package com.intp.study.dashboard.dto;

import com.intp.study.reminder.dto.DailyReminderStatusDto;
import com.intp.study.review.dto.ReviewTaskDto;

import java.util.List;

public record DashboardSummaryDto(
        String today,
        DashboardCountsDto counts,
        DailyReminderStatusDto reminder,
        List<ReviewTaskDto> dueReviewTasks,
        List<LowMasteryCardDto> lowMasteryCards,
        List<RecentBlockerDto> recentBlockers,
        List<OpenParkingQuestionDto> openParkingQuestions,
        List<RecentKnowledgeLinkDto> recentKnowledgeLinks
) {
}
