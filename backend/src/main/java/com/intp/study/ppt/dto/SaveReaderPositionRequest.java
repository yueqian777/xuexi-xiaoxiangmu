package com.intp.study.ppt.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record SaveReaderPositionRequest(
        @NotNull @Positive Long deckId,
        @Positive Integer slideNumber
) {
}
