package com.intp.study.admin.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

public record CreateInviteRequest(
        String role,
        @Min(1) @Max(1000) int maxUses,
        @Min(0) @Max(3650) int expiresInDays,
        @Min(0) long uploadQuotaBytes
) {
}
