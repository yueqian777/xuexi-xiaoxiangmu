package com.intp.study.ai.model;

public record AiGenerateCommand(
        String prompt,
        String model,
        int maxOutputTokens,
        String reasoningDepth,
        String apiKey
) {
}
