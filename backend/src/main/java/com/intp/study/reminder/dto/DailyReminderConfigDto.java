package com.intp.study.reminder.dto;

public record DailyReminderConfigDto(
        boolean enabled,
        String time
) {
}
