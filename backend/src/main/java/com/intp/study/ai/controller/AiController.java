package com.intp.study.ai.controller;

import com.intp.study.ai.dto.DefaultApiConfigDto;
import com.intp.study.ai.dto.GenerateTextRequest;
import com.intp.study.ai.dto.GenerateTextResponse;
import com.intp.study.ai.service.ApiProviderCommandService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ai")
public class AiController {
    private final ApiProviderCommandService apiProviderCommandService;

    public AiController(ApiProviderCommandService apiProviderCommandService) {
        this.apiProviderCommandService = apiProviderCommandService;
    }

    @GetMapping("/default-config")
    public DefaultApiConfigDto getDefaultConfig() {
        return apiProviderCommandService.getDefaultConfig();
    }

    @PutMapping("/default-config")
    public DefaultApiConfigDto saveDefaultConfig(@RequestBody DefaultApiConfigDto request) {
        return apiProviderCommandService.saveDefaultConfig(request);
    }

    @PostMapping("/generate")
    public GenerateTextResponse generate(@Valid @RequestBody GenerateTextRequest request) {
        return apiProviderCommandService.generate(request);
    }
}
