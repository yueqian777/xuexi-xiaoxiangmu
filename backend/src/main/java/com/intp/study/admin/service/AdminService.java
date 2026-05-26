package com.intp.study.admin.service;

import com.intp.study.admin.dto.CreateInviteRequest;
import com.intp.study.admin.dto.InviteDto;
import com.intp.study.admin.dto.UpdateActiveRequest;
import com.intp.study.admin.dto.UpdateUserQuotaRequest;
import com.intp.study.admin.dto.UserAdminDto;
import com.intp.study.auth.model.CurrentUser;
import com.intp.study.common.error.ForbiddenException;
import com.intp.study.common.error.ResourceNotFoundException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class AdminService {
    private static final long DEFAULT_UPLOAD_QUOTA_BYTES = 536_870_912L;

    private final JdbcTemplate jdbcTemplate;
    private final AdminGuard adminGuard;
    private final SecureRandom secureRandom = new SecureRandom();

    public AdminService(JdbcTemplate jdbcTemplate, AdminGuard adminGuard) {
        this.jdbcTemplate = jdbcTemplate;
        this.adminGuard = adminGuard;
    }

    public List<UserAdminDto> listUsers() {
        adminGuard.requireAdmin();
        Map<Long, Long> usageByUser = uploadUsageByUser();
        return jdbcTemplate.query("""
                SELECT id, username, display_name, role, is_active, upload_quota_bytes, created_at, updated_at
                FROM users
                ORDER BY role DESC, id ASC
                """, (rs, rowNum) -> {
            long userId = rs.getLong("id");
            String role = rs.getString("role");
            long quota = "admin".equals(role) ? 0 : rs.getLong("upload_quota_bytes");
            return new UserAdminDto(
                    userId,
                    rs.getString("username"),
                    rs.getString("display_name"),
                    role,
                    rs.getInt("is_active") != 0,
                    quota,
                    usageByUser.getOrDefault(userId, 0L),
                    rs.getString("created_at"),
                    rs.getString("updated_at")
            );
        });
    }

    public List<InviteDto> listInvites() {
        adminGuard.requireAdmin();
        return jdbcTemplate.query("""
                SELECT i.code, i.role, i.created_by, u.username AS created_by_name,
                       i.max_uses, i.used_count, i.expires_at, i.upload_quota_bytes,
                       i.is_active, i.created_at, i.updated_at
                FROM invites i
                LEFT JOIN users u ON u.id = i.created_by
                ORDER BY i.created_at DESC
                """, (rs, rowNum) -> new InviteDto(
                rs.getString("code"),
                rs.getString("role"),
                rs.getObject("created_by", Long.class),
                rs.getString("created_by_name"),
                rs.getInt("max_uses"),
                rs.getInt("used_count"),
                rs.getString("expires_at"),
                rs.getLong("upload_quota_bytes"),
                rs.getInt("is_active") != 0,
                rs.getString("created_at"),
                rs.getString("updated_at")
        ));
    }

    @Transactional
    public InviteDto createInvite(CreateInviteRequest request) {
        CurrentUser admin = adminGuard.requireAdmin();
        String code = generateInviteCode();
        String role = request.role() == null || request.role().isBlank() ? "user" : request.role();
        long quota = request.uploadQuotaBytes() > 0 ? request.uploadQuotaBytes() : DEFAULT_UPLOAD_QUOTA_BYTES;
        String expiresAt = request.expiresInDays() > 0
                ? LocalDateTime.now().plusDays(request.expiresInDays()).withNano(0).toString()
                : null;
        jdbcTemplate.update("""
                INSERT INTO invites (code, role, created_by, max_uses, used_count, expires_at, upload_quota_bytes, is_active)
                VALUES (?, ?, ?, ?, 0, ?, ?, 1)
                """, code, role, admin.id(), request.maxUses(), expiresAt, quota);
        return findInvite(code);
    }

    @Transactional
    public UserAdminDto setUserActive(long userId, UpdateActiveRequest request) {
        CurrentUser admin = adminGuard.requireAdmin();
        if (admin.id() == userId && !request.active()) {
            throw new ForbiddenException("Current admin cannot disable itself.");
        }
        int updated = jdbcTemplate.update("""
                UPDATE users
                SET is_active = ?, updated_at = datetime('now', 'localtime')
                WHERE id = ?
                """, request.active() ? 1 : 0, userId);
        if (updated == 0) {
            throw new ResourceNotFoundException("User not found.");
        }
        return findUser(userId);
    }

    @Transactional
    public UserAdminDto setUserQuota(long userId, UpdateUserQuotaRequest request) {
        adminGuard.requireAdmin();
        int updated = jdbcTemplate.update("""
                UPDATE users
                SET upload_quota_bytes = ?, updated_at = datetime('now', 'localtime')
                WHERE id = ?
                """, request.uploadQuotaBytes(), userId);
        if (updated == 0) {
            throw new ResourceNotFoundException("User not found.");
        }
        return findUser(userId);
    }

    @Transactional
    public void deleteUser(long userId) {
        CurrentUser admin = adminGuard.requireAdmin();
        if (admin.id() == userId) {
            throw new ForbiddenException("Current admin cannot delete itself.");
        }
        String role = jdbcTemplate.query("""
                SELECT role
                FROM users
                WHERE id = ?
                """, (rs, rowNum) -> rs.getString("role"), userId).stream()
                .findFirst()
                .orElseThrow(() -> new ResourceNotFoundException("User not found."));
        if ("admin".equals(role)) {
            throw new ForbiddenException("Admin user cannot be deleted.");
        }

        for (String table : List.of(
                "branch_questions",
                "mainline_anchors",
                "review_tasks",
                "mistakes",
                "knowledge_links",
                "knowledge_cards",
                "parking_lot",
                "slide_questions",
                "slide_explanations",
                "ppt_slides",
                "ppt_decks",
                "study_sessions",
                "daily_review_logs",
                "daily_ai_review_plans"
        )) {
            jdbcTemplate.update("DELETE FROM " + table + " WHERE user_id = ?", userId);
        }
        jdbcTemplate.update("DELETE FROM invites WHERE created_by = ?", userId);
        jdbcTemplate.update("DELETE FROM users WHERE id = ?", userId);
    }

    @Transactional
    public InviteDto setInviteActive(String code, UpdateActiveRequest request) {
        adminGuard.requireAdmin();
        int updated = jdbcTemplate.update("""
                UPDATE invites
                SET is_active = ?, updated_at = datetime('now', 'localtime')
                WHERE code = ?
                """, request.active() ? 1 : 0, code);
        if (updated == 0) {
            throw new ResourceNotFoundException("Invite not found.");
        }
        return findInvite(code);
    }

    private UserAdminDto findUser(long userId) {
        return listUsers().stream()
                .filter(user -> user.id() == userId)
                .findFirst()
                .orElseThrow(() -> new ResourceNotFoundException("User not found."));
    }

    private InviteDto findInvite(String code) {
        return listInvites().stream()
                .filter(invite -> invite.code().equals(code))
                .findFirst()
                .orElseThrow(() -> new ResourceNotFoundException("Invite not found."));
    }

    private Map<Long, Long> uploadUsageByUser() {
        return jdbcTemplate.query("""
                SELECT user_id, COALESCE(SUM(LENGTH(COALESCE(file_path, ''))), 0) AS used_bytes
                FROM ppt_decks
                GROUP BY user_id
                """, (rs, rowNum) -> Map.entry(rs.getLong("user_id"), rs.getLong("used_bytes")))
                .stream()
                .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue, Long::sum));
    }

    private String generateInviteCode() {
        byte[] bytes = new byte[16];
        secureRandom.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
