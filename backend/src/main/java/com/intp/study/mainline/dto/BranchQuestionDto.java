package com.intp.study.mainline.dto;

public record BranchQuestionDto(
        long id,
        long sessionId,
        long anchorId,
        String question,
        String answerSummary,
        boolean understood,
        boolean needReview,
        String createdAt,
        String anchorCode,
        String anchorTitle
) {
}
