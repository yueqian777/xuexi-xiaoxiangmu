package com.intp.study.ai.controller;

import com.intp.study.ai.dto.ApiProviderDto;
import com.intp.study.ai.dto.GenerateTextResponse;
import com.intp.study.ai.dto.ProviderTestRequest;
import com.intp.study.ai.dto.ReorderApiProviderRequest;
import com.intp.study.ai.dto.SaveApiProviderRequest;
import com.intp.study.ai.service.ApiProviderCommandService;
import com.intp.study.ai.service.ApiProviderQueryService;
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
@RequestMapping("/api/ai/providers")
public class ApiProviderController {
    private final ApiProviderQueryService apiProviderQueryService;
    private final ApiProviderCommandService apiProviderCommandService;

    public ApiProviderController(
            ApiProviderQueryService apiProviderQueryService,
            ApiProviderCommandService apiProviderCommandService
    ) {
        this.apiProviderQueryService = apiProviderQueryService;
        this.apiProviderCommandService = apiProviderCommandService;
    }

    @GetMapping
    public List<ApiProviderDto> list() {
        return apiProviderQueryService.listProviders();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ApiProviderDto create(@Valid @RequestBody SaveApiProviderRequest request) {
        return apiProviderCommandService.create(request);
    }

    @GetMapping("/{providerKey}")
    public ApiProviderDto get(@PathVariable String providerKey) {
        return apiProviderQueryService.findProvider(providerKey)
                .orElseThrow(() -> new com.intp.study.common.error.ResourceNotFoundException("API provider not found."));
    }

    @PutMapping("/{providerKey}")
    public ApiProviderDto update(@PathVariable String providerKey, @Valid @RequestBody SaveApiProviderRequest request) {
        return apiProviderCommandService.update(providerKey, request);
    }

    @DeleteMapping("/{providerKey}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable String providerKey) {
        apiProviderCommandService.delete(providerKey);
    }

    @PostMapping("/reorder")
    public List<ApiProviderDto> reorder(@RequestBody List<ReorderApiProviderRequest> request) {
        return apiProviderCommandService.reorder(request);
    }

    @PostMapping("/{providerKey}/test")
    public GenerateTextResponse test(@PathVariable String providerKey, @RequestBody(required = false) ProviderTestRequest request) {
        return apiProviderCommandService.testProvider(providerKey, request);
    }
}
