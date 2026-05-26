package com.intp.study.mainline.dto;

import jakarta.validation.constraints.NotBlank;

public record SaveBranchQuestionRequest(
        long anchorId,
        @NotBlank String question,
        String answerSummary,
        boolean understood,
        boolean needReview
) {
}
