package com.intp.study.knowledge.link.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record SaveKnowledgeLinkRequest(
        @NotNull @Positive Long sourceKnowledgeId,
        @NotNull @Positive Long targetKnowledgeId,
        String relationType,
        String relationNote,
        String comparePoints
) {
}
