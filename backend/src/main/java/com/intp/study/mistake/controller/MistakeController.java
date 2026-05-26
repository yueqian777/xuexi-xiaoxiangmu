package com.intp.study.mistake.controller;

import com.intp.study.mistake.dto.MistakeDto;
import com.intp.study.mistake.service.MistakeQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/mistakes")
public class MistakeController {
    private final MistakeQueryService mistakeQueryService;

    public MistakeController(MistakeQueryService mistakeQueryService) {
        this.mistakeQueryService = mistakeQueryService;
    }

    @GetMapping
    public List<MistakeDto> list() {
        return mistakeQueryService.listForCurrentUser();
    }
}
