package com.intp.study.study.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;

public record SaveStudySessionRequest(
        @NotBlank String date,
        @NotBlank String subject,
        String chapter,
        @NotBlank String title,
        @NotBlank String mainQuestion,
        String masteredContent,
        String blockers,
        String wrongQuestions,
        String summary,
        @Min(0) @Max(100) int mastery,
        boolean needReview,
        boolean key,
        boolean createKnowledgeCard
) {
}
