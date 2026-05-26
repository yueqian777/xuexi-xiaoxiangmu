package com.intp.study.dashboard.dto;

public record RecentBlockerDto(
        long id,
        String date,
        String subject,
        String title,
        String blockers,
        int mastery
) {
}
