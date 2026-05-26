package com.intp.study.ai.dto;

public record ApiProviderDto(
        String providerKey,
        String name,
        String providerType,
        String baseUrl,
        String model,
        String authType,
        String extraHeadersJson,
        String requestTemplateJson,
        String responsePath,
        boolean balanceQueryEnabled,
        String balanceQueryType,
        String balanceQueryConfigJson,
        boolean enabled,
        int sortOrder,
        String createdAt,
        String updatedAt
) {
}
