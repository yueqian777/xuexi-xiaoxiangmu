package com.intp.study.review.dto;

import jakarta.validation.constraints.NotBlank;

public record MarkReviewResultRequest(
        @NotBlank String result
) {
}
