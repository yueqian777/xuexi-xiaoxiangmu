package com.intp.study.ai.model;

public record AiGenerateResult(
        String text,
        String providerKey,
        String model
) {
}
