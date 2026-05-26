package com.intp.study.mainline.dto;

public record MainlineAnchorDto(
        long id,
        long sessionId,
        String anchorCode,
        String title,
        String content,
        int orderIndex,
        String sessionDate,
        String sessionSubject,
        String sessionTitle
) {
}
