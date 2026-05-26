package com.intp.study.study.dto;

public record StudySessionDto(
        long id,
        String date,
        String subject,
        String chapter,
        String title,
        String mainQuestion,
        String masteredContent,
        String blockers,
        String wrongQuestions,
        String summary,
        int mastery,
        boolean needReview,
        boolean key,
        String createdAt
) {
}

