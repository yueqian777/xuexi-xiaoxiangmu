package com.intp.study.secret.dto;

import jakarta.validation.constraints.NotBlank;

public record UnlockVaultRequest(
        @NotBlank String masterPassword
) {
}
