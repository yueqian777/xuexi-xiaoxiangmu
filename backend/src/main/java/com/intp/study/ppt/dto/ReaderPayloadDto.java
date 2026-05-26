package com.intp.study.ppt.dto;

import java.util.List;

public record ReaderPayloadDto(
        DeckDto deck,
        List<ReaderSlideDto> slides,
        List<SectionDto> sections,
        ReaderPositionDto lastPosition,
        int initialSlideNumber
) {
}
