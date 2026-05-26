package com.intp.study.auth.repository;

import com.intp.study.auth.model.CurrentUser;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Optional;

@Repository
public class UserRepository {
    private static final DateTimeFormatter SQLITE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final JdbcTemplate jdbcTemplate;

    private final RowMapper<UserRow> userRowMapper = (rs, rowNum) -> new UserRow(
            rs.getLong("id"),
            rs.getString("username"),
            rs.getString("display_name"),
            rs.getString("password_hash"),
            rs.getString("role"),
            rs.getInt("is_active") != 0,
            rs.getLong("upload_quota_bytes")
    );

    public UserRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public boolean hasInitializedAdmin() {
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM users
                WHERE role = 'admin'
                  AND is_active = 1
                  AND TRIM(COALESCE(password_hash, '')) != ''
                """, Integer.class);
        return count != null && count > 0;
    }

    public Optional<UserRow> findByUsername(String username) {
        return jdbcTemplate.query("""
                SELECT id, username, display_name, password_hash, role, is_active, upload_quota_bytes
                FROM users
                WHERE username = ?
                """, userRowMapper, username).stream().findFirst();
    }

    public Optional<UserRow> findById(long id) {
        return jdbcTemplate.query("""
                SELECT id, username, display_name, password_hash, role, is_active, upload_quota_bytes
                FROM users
                WHERE id = ?
                """, userRowMapper, id).stream().findFirst();
    }

    public long createUser(String username, String displayName, String passwordHash, String role, long uploadQuotaBytes) {
        jdbcTemplate.update("""
                INSERT INTO users (username, display_name, password_hash, role, upload_quota_bytes)
                VALUES (?, ?, ?, ?, ?)
                """, username, displayName, passwordHash, role, uploadQuotaBytes);
        Number id = jdbcTemplate.queryForObject("SELECT last_insert_rowid()", Number.class);
        return id == null ? 0L : id.longValue();
    }

    public Optional<InviteRow> findActiveInvite(String code) {
        return jdbcTemplate.query("""
                SELECT code, role, max_uses, used_count, expires_at, upload_quota_bytes, is_active
                FROM invites
                WHERE code = ?
                """, (rs, rowNum) -> new InviteRow(
                rs.getString("code"),
                rs.getString("role"),
                rs.getInt("max_uses"),
                rs.getInt("used_count"),
                rs.getString("expires_at"),
                rs.getLong("upload_quota_bytes"),
                rs.getInt("is_active") != 0
        ), code).stream().findFirst();
    }

    public void incrementInviteUse(String code) {
        jdbcTemplate.update("""
                UPDATE invites
                SET used_count = used_count + 1,
                    updated_at = datetime('now', 'localtime')
                WHERE code = ?
                """, code);
    }

    public CurrentUser toCurrentUser(UserRow row) {
        String displayName = row.displayName() == null || row.displayName().isBlank() ? row.username() : row.displayName();
        String role = row.role() == null || row.role().isBlank() ? "user" : row.role();
        return new CurrentUser(row.id(), row.username(), displayName, role);
    }

    public boolean isExpired(InviteRow invite) {
        if (invite.expiresAt() == null || invite.expiresAt().isBlank()) {
            return false;
        }
        LocalDateTime expiresAt = LocalDateTime.parse(invite.expiresAt().replace('T', ' ').substring(0, 19), SQLITE_TIME);
        return expiresAt.isBefore(LocalDateTime.now());
    }

    public record UserRow(
            long id,
            String username,
            String displayName,
            String passwordHash,
            String role,
            boolean active,
            long uploadQuotaBytes
    ) {
    }

    public record InviteRow(
            String code,
            String role,
            int maxUses,
            int usedCount,
            String expiresAt,
            long uploadQuotaBytes,
            boolean active
    ) {
    }
}

