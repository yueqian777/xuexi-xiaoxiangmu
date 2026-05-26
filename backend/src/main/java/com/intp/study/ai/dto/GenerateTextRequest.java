package com.intp.study.ai.dto;

import jakarta.validation.constraints.NotBlank;

public record GenerateTextRequest(
        String providerKey,
        String model,
        @NotBlank String prompt,
        Integer maxOutputTokens,
        String reasoningDepth,
        String apiKey
) {
}
