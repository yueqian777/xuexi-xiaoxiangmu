package com.intp.study.parking.dto;

public record ParkingLotItemDto(
        long id,
        String subject,
        String question,
        String source,
        String status,
        String createdAt
) {
}
