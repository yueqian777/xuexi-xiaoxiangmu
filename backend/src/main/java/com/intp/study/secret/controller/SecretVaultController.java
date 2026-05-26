package com.intp.study.secret.controller;

import com.intp.study.secret.dto.ProviderSecretPublicDto;
import com.intp.study.secret.dto.UnlockVaultRequest;
import com.intp.study.secret.dto.UpsertProviderSecretRequest;
import com.intp.study.secret.dto.VaultStatusDto;
import com.intp.study.secret.service.SecretVaultService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/secrets")
public class SecretVaultController {
    private final SecretVaultService secretVaultService;

    public SecretVaultController(SecretVaultService secretVaultService) {
        this.secretVaultService = secretVaultService;
    }

    @GetMapping("/status")
    public VaultStatusDto status() {
        return secretVaultService.status();
    }

    @PostMapping("/unlock")
    public VaultStatusDto unlock(@Valid @RequestBody UnlockVaultRequest request) {
        return secretVaultService.unlock(request);
    }

    @PostMapping("/lock")
    public VaultStatusDto lock() {
        return secretVaultService.lock();
    }

    @GetMapping("/providers")
    public List<ProviderSecretPublicDto> listProviders() {
        return secretVaultService.listPublicIndex();
    }

    @PutMapping("/providers/{providerKey}")
    public ProviderSecretPublicDto upsertProviderSecret(
            @PathVariable String providerKey,
            @Valid @RequestBody UpsertProviderSecretRequest request
    ) {
        return secretVaultService.upsert(providerKey, request);
    }

    @DeleteMapping("/providers/{providerKey}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteProviderSecret(@PathVariable String providerKey) {
        secretVaultService.delete(providerKey);
    }
}
