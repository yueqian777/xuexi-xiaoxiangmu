package com.intp.study.common.tenant;

import com.intp.study.auth.AuthSession;
import com.intp.study.auth.model.CurrentUser;
import jakarta.servlet.http.HttpSession;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.OptionalLong;

@Component
public class SessionCurrentUserProvider implements CurrentUserProvider {
    private final HttpSession session;
    private final JdbcTemplate jdbcTemplate;

    public SessionCurrentUserProvider(HttpSession session, JdbcTemplate jdbcTemplate) {
        this.session = session;
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public OptionalLong currentUserId() {
        Object raw = session.getAttribute(AuthSession.CURRENT_USER);
        if (raw instanceof CurrentUser user) {
            if (isActiveUser(user.id())) {
                return OptionalLong.of(user.id());
            }
            session.invalidate();
        }
        return OptionalLong.empty();
    }

    private boolean isActiveUser(long userId) {
        List<Integer> rows = jdbcTemplate.query("""
                SELECT is_active
                FROM users
                WHERE id = ?
                """, (rs, rowNum) -> rs.getInt("is_active"), userId);
        return !rows.isEmpty() && rows.getFirst() != 0;
    }
}
