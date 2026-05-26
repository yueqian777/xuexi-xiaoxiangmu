package com.intp.study.review.daily.dto;

public record DailyAiReviewPlanDto(
        long id,
        String reviewDate,
        String providerKey,
        String model,
        String planJson,
        String sourceSnapshotJson,
        String answersJson,
        String evaluationJson,
        String status,
        String createdAt,
        String evaluatedAt
) {
}
