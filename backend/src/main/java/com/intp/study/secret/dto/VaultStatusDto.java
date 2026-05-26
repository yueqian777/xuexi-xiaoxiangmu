package com.intp.study.secret.dto;

public record VaultStatusDto(
        boolean exists,
        boolean unlocked
) {
}
