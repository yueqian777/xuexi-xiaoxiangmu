package com.intp.study.review.daily.dto;

import jakarta.validation.constraints.NotBlank;

import java.util.Map;

public record EvaluateDailyAiReviewRequest(
        @NotBlank String providerKey,
        String apiKey,
        String model,
        Integer maxOutputTokens,
        Map<String, String> answers
) {
}
