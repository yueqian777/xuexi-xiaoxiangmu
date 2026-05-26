package com.intp.study.knowledge.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;

public record SaveKnowledgeCardRequest(
        @NotBlank String subject,
        @NotBlank String topic,
        String coreQuestion,
        @NotBlank String oneSentence,
        String logicOrFormula,
        String application,
        @Min(0) @Max(100) int mastery,
        boolean needReview,
        Long sourceSessionId
) {
}
