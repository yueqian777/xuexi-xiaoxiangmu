package com.intp.study.secret.dto;

import jakarta.validation.constraints.NotBlank;

public record UpsertProviderSecretRequest(
        @NotBlank String apiKey,
        String providerName,
        String model,
        String providerType,
        String baseUrl
) {
}
