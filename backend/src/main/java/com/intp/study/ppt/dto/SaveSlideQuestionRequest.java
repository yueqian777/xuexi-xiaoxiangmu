package com.intp.study.ppt.dto;

import jakarta.validation.constraints.NotBlank;

public record SaveSlideQuestionRequest(
        @NotBlank String question,
        @NotBlank String answer,
        String model,
        String category,
        Integer sortOrder,
        String status
) {
}
