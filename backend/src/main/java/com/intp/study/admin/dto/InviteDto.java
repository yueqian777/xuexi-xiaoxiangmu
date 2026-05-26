package com.intp.study.admin.dto;

public record InviteDto(
        String code,
        String role,
        Long createdBy,
        String createdByName,
        int maxUses,
        int usedCount,
        String expiresAt,
        long uploadQuotaBytes,
        boolean active,
        String createdAt,
        String updatedAt
) {
}
