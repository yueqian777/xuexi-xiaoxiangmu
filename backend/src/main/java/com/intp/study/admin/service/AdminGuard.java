package com.intp.study.admin.service;

import com.intp.study.auth.AuthSession;
import com.intp.study.auth.model.CurrentUser;
import com.intp.study.common.error.ForbiddenException;
import com.intp.study.common.error.UnauthorizedException;
import jakarta.servlet.http.HttpSession;
import org.springframework.stereotype.Component;

@Component
public class AdminGuard {
    private final HttpSession session;

    public AdminGuard(HttpSession session) {
        this.session = session;
    }

    public CurrentUser requireAdmin() {
        Object raw = session.getAttribute(AuthSession.CURRENT_USER);
        if (!(raw instanceof CurrentUser user)) {
            throw new UnauthorizedException("Authentication required.");
        }
        if (!user.isAdmin()) {
            throw new ForbiddenException("Admin role required.");
        }
        return user;
    }
}
