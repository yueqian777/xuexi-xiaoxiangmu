package com.intp.study.ai.dto;

public record ReorderApiProviderRequest(
        String providerKey,
        int sortOrder,
        boolean enabled
) {
}
