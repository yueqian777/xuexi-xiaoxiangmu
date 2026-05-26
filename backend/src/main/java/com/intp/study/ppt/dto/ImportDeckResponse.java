package com.intp.study.ppt.dto;

public record ImportDeckResponse(
        long deckId,
        String title,
        int slideCount,
        String status
) {
}
