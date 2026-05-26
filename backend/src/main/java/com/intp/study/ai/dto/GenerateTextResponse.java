package com.intp.study.ai.dto;

public record GenerateTextResponse(
        String text,
        String providerKey,
        String model
) {
}
