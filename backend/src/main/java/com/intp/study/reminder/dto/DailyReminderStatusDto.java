package com.intp.study.reminder.dto;

import com.intp.study.review.daily.dto.DailyReviewLogDto;

public record DailyReminderStatusDto(
        DailyReminderConfigDto config,
        DailyReviewLogDto todayLog,
        boolean dueNow
) {
}
