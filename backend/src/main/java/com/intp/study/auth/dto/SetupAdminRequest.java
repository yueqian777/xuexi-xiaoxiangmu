package com.intp.study.auth.dto;

import jakarta.validation.constraints.NotBlank;

public record SetupAdminRequest(
        @NotBlank String username,
        String displayName,
        @NotBlank String password
) {
}

