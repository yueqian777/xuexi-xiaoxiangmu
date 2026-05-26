package com.intp.study.dashboard.dto;

public record LowMasteryCardDto(
        long id,
        String subject,
        String topic,
        int mastery,
        String coreQuestion
) {
}
