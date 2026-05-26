package com.intp.study.auth.service;

import com.intp.study.auth.dto.LoginRequest;
import com.intp.study.auth.dto.RegisterByInviteRequest;
import com.intp.study.auth.dto.SetupAdminRequest;
import com.intp.study.auth.model.CurrentUser;
import com.intp.study.auth.repository.UserRepository;
import com.intp.study.auth.security.PasswordHasher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {
    private static final long DEFAULT_UPLOAD_QUOTA_BYTES = 536_870_912L;

    private final UserRepository userRepository;
    private final PasswordHasher passwordHasher;

    public AuthService(UserRepository userRepository, PasswordHasher passwordHasher) {
        this.userRepository = userRepository;
        this.passwordHasher = passwordHasher;
    }

    public boolean hasInitializedAdmin() {
        return userRepository.hasInitializedAdmin();
    }

    @Transactional
    public CurrentUser initializeFirstAdmin(SetupAdminRequest request) {
        if (hasInitializedAdmin()) {
            throw new IllegalArgumentException("系统已经存在可用管理员，无需再次初始化。");
        }
        String username = normalizeUsername(request.username());
        if (userRepository.findByUsername(username).isPresent()) {
            throw new IllegalArgumentException("用户名已存在。");
        }
        String displayName = normalizeDisplayName(request.displayName(), username);
        long id = userRepository.createUser(username, displayName, passwordHasher.hash(request.password()), "admin", DEFAULT_UPLOAD_QUOTA_BYTES);
        return userRepository.toCurrentUser(userRepository.findById(id).orElseThrow());
    }

    public CurrentUser login(LoginRequest request) {
        String username = normalizeUsername(request.username());
        UserRepository.UserRow user = userRepository.findByUsername(username)
                .orElseThrow(() -> new IllegalArgumentException("用户名或密码错误。"));
        if (!user.active()) {
            throw new IllegalArgumentException("账户已被停用。");
        }
        if (!passwordHasher.verify(request.password(), user.passwordHash())) {
            throw new IllegalArgumentException("用户名或密码错误。");
        }
        return userRepository.toCurrentUser(user);
    }

    @Transactional
    public CurrentUser registerByInvite(RegisterByInviteRequest request) {
        String username = normalizeUsername(request.username());
        if (userRepository.findByUsername(username).isPresent()) {
            throw new IllegalArgumentException("用户名已存在。");
        }
        UserRepository.InviteRow invite = userRepository.findActiveInvite(request.inviteCode().trim())
                .orElseThrow(() -> new IllegalArgumentException("邀请码无效。"));
        if (!invite.active()) {
            throw new IllegalArgumentException("邀请码已停用。");
        }
        if (invite.usedCount() >= invite.maxUses()) {
            throw new IllegalArgumentException("邀请码使用次数已达上限。");
        }
        if (userRepository.isExpired(invite)) {
            throw new IllegalArgumentException("邀请码已过期。");
        }
        String displayName = normalizeDisplayName(request.displayName(), username);
        String role = invite.role() == null || invite.role().isBlank() ? "user" : invite.role();
        long quota = invite.uploadQuotaBytes() > 0 ? invite.uploadQuotaBytes() : DEFAULT_UPLOAD_QUOTA_BYTES;
        long id = userRepository.createUser(username, displayName, passwordHasher.hash(request.password()), role, quota);
        userRepository.incrementInviteUse(invite.code());
        return userRepository.toCurrentUser(userRepository.findById(id).orElseThrow());
    }

    private String normalizeUsername(String username) {
        String normalized = username == null ? "" : username.trim();
        if (normalized.isBlank()) {
            throw new IllegalArgumentException("用户名不能为空。");
        }
        return normalized;
    }

    private String normalizeDisplayName(String displayName, String username) {
        String normalized = displayName == null ? "" : displayName.trim();
        return normalized.isBlank() ? username : normalized;
    }
}

