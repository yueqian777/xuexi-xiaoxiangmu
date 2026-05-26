package com.intp.study.ppt.dto;

public record SlideQuestionDto(
        long id,
        long slideId,
        String question,
        String answer,
        String model,
        String category,
        int sortOrder,
        String status,
        String createdAt
) {
}
