package com.intp.study.dashboard.dto;

public record OpenParkingQuestionDto(
        long id,
        String subject,
        String question,
        String source,
        String status,
        String createdAt
) {
}
