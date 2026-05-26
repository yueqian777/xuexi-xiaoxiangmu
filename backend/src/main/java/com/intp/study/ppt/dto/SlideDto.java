package com.intp.study.ppt.dto;

public record SlideDto(
        long id,
        long deckId,
        int slideNumber,
        String title,
        String slideText,
        String notes,
        String imagePath,
        int sectionIndex,
        String pageType,
        String oneSentenceSummary,
        String slideRole,
        String keyPoints,
        String createdAt
) {
}
