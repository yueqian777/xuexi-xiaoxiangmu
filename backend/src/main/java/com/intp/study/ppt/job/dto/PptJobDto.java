package com.intp.study.ppt.job.dto;

public record PptJobDto(
        String id,
        long deckId,
        String jobType,
        String status,
        int progress,
        String statusText,
        boolean stopRequested,
        String createdAt,
        String updatedAt
) {
}
