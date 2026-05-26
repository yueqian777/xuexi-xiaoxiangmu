package com.intp.study.admin.dto;

public record UserAdminDto(
        long id,
        String username,
        String displayName,
        String role,
        boolean active,
        long uploadQuotaBytes,
        long usedBytes,
        String createdAt,
        String updatedAt
) {
}
