package com.intp.study.ppt.dto;

import jakarta.validation.constraints.NotBlank;

public record SaveSlideExplanationRequest(
        String model,
        @NotBlank String explanation
) {
}
