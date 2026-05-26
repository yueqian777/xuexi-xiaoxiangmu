package com.intp.study.knowledge.link.dto;

public record KnowledgeLinkDto(
        long id,
        long sourceKnowledgeId,
        long targetKnowledgeId,
        String relationType,
        String relationNote,
        String comparePoints,
        String createdAt,
        String sourceTopic,
        String sourceOneSentence,
        String targetTopic,
        String targetOneSentence
) {
}
