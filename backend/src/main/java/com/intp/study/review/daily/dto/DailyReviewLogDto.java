package com.intp.study.review.daily.dto;

public record DailyReviewLogDto(
        long id,
        String reviewDate,
        String status,
        String notes,
        String createdAt
) {
}
