package com.intp.study.auth.controller;

import com.intp.study.auth.AuthSession;
import com.intp.study.auth.dto.CurrentUserResponse;
import com.intp.study.auth.dto.LoginRequest;
import com.intp.study.auth.dto.RegisterByInviteRequest;
import com.intp.study.auth.dto.SetupAdminRequest;
import com.intp.study.auth.dto.SystemStatusResponse;
import com.intp.study.auth.model.CurrentUser;
import com.intp.study.auth.service.AuthService;
import com.intp.study.common.error.UnauthorizedException;
import jakarta.servlet.http.HttpSession;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @GetMapping("/status")
    public SystemStatusResponse status() {
        return new SystemStatusResponse(authService.hasInitializedAdmin());
    }

    @PostMapping("/setup-admin")
    public CurrentUserResponse setupAdmin(@Valid @RequestBody SetupAdminRequest request, HttpSession session) {
        CurrentUser user = authService.initializeFirstAdmin(request);
        session.setAttribute(AuthSession.CURRENT_USER, user);
        return CurrentUserResponse.from(user);
    }

    @PostMapping("/login")
    public CurrentUserResponse login(@Valid @RequestBody LoginRequest request, HttpSession session) {
        CurrentUser user = authService.login(request);
        session.setAttribute(AuthSession.CURRENT_USER, user);
        return CurrentUserResponse.from(user);
    }

    @PostMapping("/register-by-invite")
    public CurrentUserResponse registerByInvite(@Valid @RequestBody RegisterByInviteRequest request, HttpSession session) {
        CurrentUser user = authService.registerByInvite(request);
        session.setAttribute(AuthSession.CURRENT_USER, user);
        return CurrentUserResponse.from(user);
    }

    @PostMapping("/logout")
    public Map<String, Object> logout(HttpSession session) {
        session.invalidate();
        return Map.of("ok", true);
    }

    @GetMapping("/me")
    public CurrentUserResponse me(HttpSession session) {
        Object raw = session.getAttribute(AuthSession.CURRENT_USER);
        if (raw instanceof CurrentUser user) {
            return CurrentUserResponse.from(user);
        }
        throw new UnauthorizedException("No authenticated user is available.");
    }
}
