package com.intp.study.knowledge.link.controller;

import com.intp.study.knowledge.link.dto.KnowledgeLinkDto;
import com.intp.study.knowledge.link.dto.SaveKnowledgeLinkRequest;
import com.intp.study.knowledge.link.service.KnowledgeLinkCommandService;
import com.intp.study.knowledge.link.service.KnowledgeLinkQueryService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class KnowledgeLinkController {
    private final KnowledgeLinkQueryService knowledgeLinkQueryService;
    private final KnowledgeLinkCommandService knowledgeLinkCommandService;

    public KnowledgeLinkController(
            KnowledgeLinkQueryService knowledgeLinkQueryService,
            KnowledgeLinkCommandService knowledgeLinkCommandService
    ) {
        this.knowledgeLinkQueryService = knowledgeLinkQueryService;
        this.knowledgeLinkCommandService = knowledgeLinkCommandService;
    }

    @GetMapping("/api/knowledge-links")
    public List<KnowledgeLinkDto> list() {
        return knowledgeLinkQueryService.listForCurrentUser();
    }

    @GetMapping("/api/knowledge-cards/{cardId}/links")
    public List<KnowledgeLinkDto> listForCard(@PathVariable long cardId) {
        return knowledgeLinkQueryService.listForCard(cardId);
    }

    @PostMapping("/api/knowledge-links")
    @ResponseStatus(HttpStatus.CREATED)
    public KnowledgeLinkDto upsert(@Valid @RequestBody SaveKnowledgeLinkRequest request) {
        return knowledgeLinkCommandService.upsert(request);
    }

    @DeleteMapping("/api/knowledge-links/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable long id) {
        knowledgeLinkCommandService.delete(id);
    }
}
