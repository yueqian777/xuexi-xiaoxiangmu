package com.intp.study.mistake.dto;

public record SaveMistakeRequest(
        String subject,
        String topic,
        Long knowledgeId,
        @jakarta.validation.constraints.NotBlank String originalQuestion,
        String myWrongAnswer,
        @jakarta.validation.constraints.NotBlank String correctIdea,
        @jakarta.validation.constraints.NotBlank String causeCategory,
        String warningSignal,
        String summary,
        boolean addToReview
) {
}
