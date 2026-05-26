package com.intp.study.ai.dto;

import jakarta.validation.constraints.NotBlank;

public record SaveApiProviderRequest(
        @NotBlank String name,
        @NotBlank String providerType,
        String baseUrl,
        String model,
        String apiKeyEnv,
        String authType,
        String extraHeadersJson,
        String requestTemplateJson,
        String responsePath,
        boolean balanceQueryEnabled,
        String balanceQueryType,
        String balanceQueryConfigJson,
        boolean enabled,
        int sortOrder
) {
}
