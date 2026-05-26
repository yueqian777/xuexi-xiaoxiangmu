package com.intp.study.mistake.controller;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.mistake.dto.MistakeDto;
import com.intp.study.mistake.dto.SaveMistakeRequest;
import com.intp.study.mistake.service.MistakeCommandService;
import com.intp.study.mistake.service.MistakeQueryService;
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
@RequestMapping("/api/mistakes")
public class MistakeController {
    private final MistakeQueryService mistakeQueryService;
    private final MistakeCommandService mistakeCommandService;

    public MistakeController(MistakeQueryService mistakeQueryService, MistakeCommandService mistakeCommandService) {
        this.mistakeQueryService = mistakeQueryService;
        this.mistakeCommandService = mistakeCommandService;
    }

    @GetMapping
    public List<MistakeDto> list() {
        return mistakeQueryService.listForCurrentUser();
    }

    @GetMapping("/{id}")
    public MistakeDto get(@PathVariable long id) {
        return mistakeQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Mistake not found."));
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public MistakeDto create(@Valid @RequestBody SaveMistakeRequest request) {
        return mistakeCommandService.create(request);
    }

    @PutMapping("/{id}")
    public MistakeDto update(@PathVariable long id, @Valid @RequestBody SaveMistakeRequest request) {
        return mistakeCommandService.update(id, request);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable long id) {
        mistakeCommandService.delete(id);
    }
}
