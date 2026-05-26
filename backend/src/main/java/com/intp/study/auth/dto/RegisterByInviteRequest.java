package com.intp.study.auth.dto;

import jakarta.validation.constraints.NotBlank;

public record RegisterByInviteRequest(
        @NotBlank String username,
        String displayName,
        @NotBlank String password,
        @NotBlank String inviteCode
) {
}

