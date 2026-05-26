package com.intp.study.review.dto;

public record ReviewTaskDto(
        long id,
        long knowledgeId,
        String reviewDate,
        String reviewStage,
        String status,
        String result,
        String createdAt,
        String subject,
        String topic,
        String coreQuestion,
        String oneSentence,
        int mastery
) {
}
