package com.intp.study.ppt.controller;

import com.intp.study.ppt.dto.DeckDto;
import com.intp.study.ppt.dto.SectionDto;
import com.intp.study.ppt.dto.SlideDto;
import com.intp.study.ppt.service.PptDeckQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/ppt/decks")
public class PptDeckController {
    private final PptDeckQueryService pptDeckQueryService;

    public PptDeckController(PptDeckQueryService pptDeckQueryService) {
        this.pptDeckQueryService = pptDeckQueryService;
    }

    @GetMapping
    public List<DeckDto> list() {
        return pptDeckQueryService.listForCurrentUser();
    }

    @GetMapping("/{deckId}")
    public DeckDto get(@PathVariable long deckId) {
        return pptDeckQueryService.findForCurrentUser(deckId)
                .orElseThrow(() -> new IllegalArgumentException("PPT deck not found."));
    }

    @GetMapping("/{deckId}/slides")
    public List<SlideDto> listSlides(@PathVariable long deckId) {
        return pptDeckQueryService.listSlidesForCurrentUser(deckId);
    }

    @GetMapping("/{deckId}/sections")
    public List<SectionDto> listSections(@PathVariable long deckId) {
        return pptDeckQueryService.listSectionsForCurrentUser(deckId);
    }
}
