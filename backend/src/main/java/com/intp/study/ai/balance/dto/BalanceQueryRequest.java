package com.intp.study.ai.balance.dto;

public record BalanceQueryRequest(
        String credential,
        String queryType,
        String configJson
) {
}
