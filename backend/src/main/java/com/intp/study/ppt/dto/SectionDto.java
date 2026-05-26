package com.intp.study.ppt.dto;

public record SectionDto(
        long id,
        long deckId,
        int sectionIndex,
        String title,
        String topic,
        String coreQuestion,
        String summary,
        String keyTermsJson,
        String prerequisiteConceptsJson,
        int startSlide,
        int endSlide,
        String createdAt,
        String updatedAt
) {
}
