package com.intp.study.ppt.dto;

import java.util.List;

public record ReaderSlideDto(
        SlideDto slide,
        SlideExplanationDto latestExplanation,
        List<SlideQuestionDto> questions,
        String imageUrl,
        boolean imageAvailable
) {
}
