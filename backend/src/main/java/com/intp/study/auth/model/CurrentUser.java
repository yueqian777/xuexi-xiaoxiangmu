package com.intp.study.auth.model;

import java.io.Serializable;

public record CurrentUser(
        long id,
        String username,
        String displayName,
        String role
) implements Serializable {
    public boolean isAdmin() {
        return "admin".equals(role);
    }
}

