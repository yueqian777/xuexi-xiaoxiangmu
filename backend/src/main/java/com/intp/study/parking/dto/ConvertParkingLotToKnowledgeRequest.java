package com.intp.study.parking.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;

public record ConvertParkingLotToKnowledgeRequest(
        @NotBlank String topic,
        @NotBlank String oneSentence,
        String logicOrFormula,
        String application,
        @Min(0) @Max(100) int mastery,
        boolean needReview
) {
}
