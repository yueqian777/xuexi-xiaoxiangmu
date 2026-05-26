package com.intp.study.auth.dto;

import com.intp.study.auth.model.CurrentUser;

public record CurrentUserResponse(
        long id,
        String username,
        String displayName,
        String role
) {
    public static CurrentUserResponse from(CurrentUser user) {
        return new CurrentUserResponse(user.id(), user.username(), user.displayName(), user.role());
    }
}

