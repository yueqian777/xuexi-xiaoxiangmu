package com.intp.study.ai.controller;

import com.intp.study.ai.dto.ApiProviderDto;
import com.intp.study.ai.service.ApiProviderQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/ai/providers")
public class ApiProviderController {
    private final ApiProviderQueryService apiProviderQueryService;

    public ApiProviderController(ApiProviderQueryService apiProviderQueryService) {
        this.apiProviderQueryService = apiProviderQueryService;
    }

    @GetMapping
    public List<ApiProviderDto> list() {
        return apiProviderQueryService.listProviders();
    }
}
