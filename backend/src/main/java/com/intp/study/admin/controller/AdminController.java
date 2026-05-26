package com.intp.study.admin.controller;

import com.intp.study.admin.dto.CreateInviteRequest;
import com.intp.study.admin.dto.InviteDto;
import com.intp.study.admin.dto.UpdateActiveRequest;
import com.intp.study.admin.dto.UpdateUserQuotaRequest;
import com.intp.study.admin.dto.UserAdminDto;
import com.intp.study.admin.service.AdminService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/admin")
public class AdminController {
    private final AdminService adminService;

    public AdminController(AdminService adminService) {
        this.adminService = adminService;
    }

    @GetMapping("/users")
    public List<UserAdminDto> listUsers() {
        return adminService.listUsers();
    }

    @PatchMapping("/users/{userId}/active")
    public UserAdminDto setUserActive(@PathVariable long userId, @RequestBody UpdateActiveRequest request) {
        return adminService.setUserActive(userId, request);
    }

    @PatchMapping("/users/{userId}/quota")
    public UserAdminDto setUserQuota(@PathVariable long userId, @Valid @RequestBody UpdateUserQuotaRequest request) {
        return adminService.setUserQuota(userId, request);
    }

    @DeleteMapping("/users/{userId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteUser(@PathVariable long userId) {
        adminService.deleteUser(userId);
    }

    @GetMapping("/invites")
    public List<InviteDto> listInvites() {
        return adminService.listInvites();
    }

    @PostMapping("/invites")
    @ResponseStatus(HttpStatus.CREATED)
    public InviteDto createInvite(@Valid @RequestBody CreateInviteRequest request) {
        return adminService.createInvite(request);
    }

    @PatchMapping("/invites/{code}/active")
    public InviteDto setInviteActive(@PathVariable String code, @RequestBody UpdateActiveRequest request) {
        return adminService.setInviteActive(code, request);
    }
}
