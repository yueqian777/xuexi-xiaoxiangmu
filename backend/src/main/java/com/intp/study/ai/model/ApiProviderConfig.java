package com.intp.study.ai.model;

public record ApiProviderConfig(
        String providerKey,
        String name,
        String providerType,
        String baseUrl,
        String model,
        String apiKeyEnv,
        String authType,
        String extraHeadersJson,
        String requestTemplateJson,
        String responsePath,
        boolean enabled,
        int sortOrder
) {
}
