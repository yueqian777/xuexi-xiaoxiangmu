package com.intp.study.ppt.dto;

public record DeckDto(
        long id,
        String filename,
        String title,
        String subject,
        String category,
        int sortOrder,
        String status,
        int slideCount,
        String outline,
        String outlineGeneratedAt,
        String createdAt
) {
}

