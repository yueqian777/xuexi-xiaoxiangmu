package com.intp.study.admin.dto;

import jakarta.validation.constraints.Min;

public record UpdateUserQuotaRequest(
        @Min(0) long uploadQuotaBytes
) {
}
