package com.intp.study.parking.dto;

import jakarta.validation.constraints.NotBlank;

public record SaveParkingLotItemRequest(
        String subject,
        @NotBlank String question,
        String source,
        String status
) {
}
