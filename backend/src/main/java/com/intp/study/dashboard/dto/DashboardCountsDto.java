package com.intp.study.dashboard.dto;

public record DashboardCountsDto(
        int dueReviewTasks,
        int lowMasteryCards,
        int recentBlockers,
        int openParkingQuestions,
        int recentKnowledgeLinks
) {
}
