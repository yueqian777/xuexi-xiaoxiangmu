package com.intp.study.mainline.dto;

import jakarta.validation.constraints.NotBlank;

public record SaveMainlineAnchorRequest(
        long sessionId,
        @NotBlank String anchorCode,
        @NotBlank String title,
        String content,
        int orderIndex
) {
}
