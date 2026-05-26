package com.intp.study.ppt.dto;

public record SlideExplanationDto(
        long id,
        long slideId,
        String model,
        String explanation,
        String createdAt
) {
}
