package com.intp.study.dashboard.dto;

public record RecentKnowledgeLinkDto(
        String relationType,
        String relationNote,
        String comparePoints,
        String createdAt,
        String sourceSubject,
        String sourceTopic,
        String targetSubject,
        String targetTopic
) {
}
