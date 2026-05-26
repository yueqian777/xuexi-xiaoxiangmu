package com.intp.study.knowledge.dto;

public record KnowledgeCardDto(
        long id,
        String subject,
        String topic,
        String coreQuestion,
        String oneSentence,
        String logicOrFormula,
        String application,
        int mastery,
        boolean needReview,
        Long sourceSessionId,
        String createdAt
) {
}
