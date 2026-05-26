package com.intp.study.knowledge.controller;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.knowledge.dto.KnowledgeCardDto;
import com.intp.study.knowledge.dto.SaveKnowledgeCardRequest;
import com.intp.study.knowledge.service.KnowledgeCardCommandService;
import com.intp.study.knowledge.service.KnowledgeCardQueryService;
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
@RequestMapping("/api/knowledge-cards")
public class KnowledgeCardController {
    private final KnowledgeCardQueryService knowledgeCardQueryService;
    private final KnowledgeCardCommandService knowledgeCardCommandService;

    public KnowledgeCardController(
            KnowledgeCardQueryService knowledgeCardQueryService,
            KnowledgeCardCommandService knowledgeCardCommandService
    ) {
        this.knowledgeCardQueryService = knowledgeCardQueryService;
        this.knowledgeCardCommandService = knowledgeCardCommandService;
    }

    @GetMapping
    public List<KnowledgeCardDto> list() {
        return knowledgeCardQueryService.listForCurrentUser();
    }

    @GetMapping("/{id}")
    public KnowledgeCardDto get(@PathVariable long id) {
        return knowledgeCardQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Knowledge card not found."));
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public KnowledgeCardDto create(@Valid @RequestBody SaveKnowledgeCardRequest request) {
        return knowledgeCardCommandService.create(request);
    }

    @PutMapping("/{id}")
    public KnowledgeCardDto update(@PathVariable long id, @Valid @RequestBody SaveKnowledgeCardRequest request) {
        return knowledgeCardCommandService.update(id, request);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable long id) {
        knowledgeCardCommandService.delete(id);
    }
}
