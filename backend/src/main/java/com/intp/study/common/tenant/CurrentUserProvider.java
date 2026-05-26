package com.intp.study.common.tenant;

import com.intp.study.common.error.UnauthorizedException;

import java.util.OptionalLong;

public interface CurrentUserProvider {
    OptionalLong currentUserId();

    default long requireUserId() {
        return currentUserId().orElseThrow(() -> new UnauthorizedException("No authenticated user is available."));
    }
}
