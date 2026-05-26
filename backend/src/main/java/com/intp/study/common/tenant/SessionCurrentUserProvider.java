package com.intp.study.common.tenant;

import com.intp.study.auth.AuthSession;
import com.intp.study.auth.model.CurrentUser;
import jakarta.servlet.http.HttpSession;
import org.springframework.stereotype.Component;

import java.util.OptionalLong;

@Component
public class SessionCurrentUserProvider implements CurrentUserProvider {
    private final HttpSession session;

    public SessionCurrentUserProvider(HttpSession session) {
        this.session = session;
    }

    @Override
    public OptionalLong currentUserId() {
        Object raw = session.getAttribute(AuthSession.CURRENT_USER);
        if (raw instanceof CurrentUser user) {
            return OptionalLong.of(user.id());
        }
        return OptionalLong.empty();
    }
}
