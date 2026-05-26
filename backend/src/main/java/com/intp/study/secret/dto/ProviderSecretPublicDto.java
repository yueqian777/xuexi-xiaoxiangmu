package com.intp.study.secret.dto;

public record ProviderSecretPublicDto(
        String providerKey,
        String providerName,
        String model,
        String providerType,
        String baseUrl,
        String updatedAt
) {
}
