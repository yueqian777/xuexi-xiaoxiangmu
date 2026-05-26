package com.intp.study.reminder.dto;

import jakarta.validation.constraints.Pattern;

public record SaveDailyReminderConfigRequest(
        Boolean enabled,
        @Pattern(regexp = "^([01]\\d|2[0-3]):[0-5]\\d$", message = "time must be HH:mm") String time
) {
}
