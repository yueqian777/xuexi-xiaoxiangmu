package com.intp.study.review.daily.dto;

import jakarta.validation.constraints.NotBlank;

public record GenerateDailyAiReviewRequest(
        @NotBlank String providerKey,
        String apiKey,
        String model,
        Integer maxOutputTokens,
        boolean regenerate
) {
}
