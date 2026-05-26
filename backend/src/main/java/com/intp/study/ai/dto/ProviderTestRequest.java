package com.intp.study.ai.dto;

public record ProviderTestRequest(
        String model,
        String apiKey,
        Integer maxOutputTokens
) {
}
