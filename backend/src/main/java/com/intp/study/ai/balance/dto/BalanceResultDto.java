package com.intp.study.ai.balance.dto;

public record BalanceResultDto(
        String kind,
        String provider,
        String title,
        Double amount,
        String unit,
        Double total,
        Double used,
        String status,
        String source,
        String detailsJson
) {
}
