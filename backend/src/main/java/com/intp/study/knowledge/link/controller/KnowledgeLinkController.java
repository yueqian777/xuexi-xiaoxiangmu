package com.intp.study.knowledge.link.controller;

import com.intp.study.knowledge.link.dto.KnowledgeLinkDto;
import com.intp.study.knowledge.link.service.KnowledgeLinkQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class KnowledgeLinkController {
    private final KnowledgeLinkQueryService knowledgeLinkQueryService;

    public KnowledgeLinkController(KnowledgeLinkQueryService knowledgeLinkQueryService) {
        this.knowledgeLinkQueryService = knowledgeLinkQueryService;
    }

    @GetMapping("/api/knowledge-links")
    public List<KnowledgeLinkDto> list() {
        return knowledgeLinkQueryService.listForCurrentUser();
    }

    @GetMapping("/api/knowledge-cards/{cardId}/links")
    public List<KnowledgeLinkDto> listForCard(@PathVariable long cardId) {
        return knowledgeLinkQueryService.listForCard(cardId);
    }
}
