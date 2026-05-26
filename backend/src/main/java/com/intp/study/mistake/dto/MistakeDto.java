package com.intp.study.mistake.dto;

public record MistakeDto(
        long id,
        String subject,
        String topic,
        Long knowledgeId,
        String originalQuestion,
        String myWrongAnswer,
        String correctIdea,
        String causeCategory,
        String warningSignal,
        String summary,
        boolean addToReview,
        String createdAt,
        String knowledgeTopic,
        String knowledgeOneSentence
) {
}
