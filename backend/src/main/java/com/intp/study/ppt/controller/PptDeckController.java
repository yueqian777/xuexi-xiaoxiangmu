package com.intp.study.ppt.controller;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.ppt.dto.DeckDto;
import com.intp.study.ppt.dto.ImportDeckResponse;
import com.intp.study.ppt.dto.ReaderPayloadDto;
import com.intp.study.ppt.dto.ReaderPositionDto;
import com.intp.study.ppt.dto.SaveReaderPositionRequest;
import com.intp.study.ppt.dto.SaveSlideExplanationRequest;
import com.intp.study.ppt.dto.SaveSlideQuestionRequest;
import com.intp.study.ppt.dto.SectionDto;
import com.intp.study.ppt.dto.SlideExplanationDto;
import com.intp.study.ppt.dto.SlideDto;
import com.intp.study.ppt.dto.SlideQuestionDto;
import com.intp.study.ppt.service.PptDeckQueryService;
import com.intp.study.ppt.service.PptImageService;
import com.intp.study.ppt.service.PptImportService;
import com.intp.study.ppt.service.PptReaderCommandService;
import jakarta.validation.Valid;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@RestController
@RequestMapping("/api/ppt/decks")
public class PptDeckController {
    private final PptDeckQueryService pptDeckQueryService;
    private final PptReaderCommandService pptReaderCommandService;
    private final PptImageService pptImageService;
    private final PptImportService pptImportService;

    public PptDeckController(
            PptDeckQueryService pptDeckQueryService,
            PptReaderCommandService pptReaderCommandService,
            PptImageService pptImageService,
            PptImportService pptImportService
    ) {
        this.pptDeckQueryService = pptDeckQueryService;
        this.pptReaderCommandService = pptReaderCommandService;
        this.pptImageService = pptImageService;
        this.pptImportService = pptImportService;
    }

    @GetMapping
    public List<DeckDto> list() {
        return pptDeckQueryService.listForCurrentUser();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ImportDeckResponse importDeck(
            @RequestPart("file") MultipartFile file,
            @RequestPart(value = "subject", required = false) String subject,
            @RequestPart(value = "title", required = false) String title
    ) {
        return pptImportService.importDeck(file, subject, title);
    }

    @GetMapping("/{deckId}")
    public DeckDto get(@PathVariable long deckId) {
        return pptDeckQueryService.findForCurrentUser(deckId)
                .orElseThrow(() -> new ResourceNotFoundException("PPT deck not found."));
    }

    @GetMapping("/{deckId}/slides")
    public List<SlideDto> listSlides(@PathVariable long deckId) {
        return pptDeckQueryService.listSlidesForCurrentUser(deckId);
    }

    @GetMapping("/{deckId}/sections")
    public List<SectionDto> listSections(@PathVariable long deckId) {
        return pptDeckQueryService.listSectionsForCurrentUser(deckId);
    }

    @GetMapping("/{deckId}/reader")
    public ReaderPayloadDto readerPayload(@PathVariable long deckId) {
        return pptDeckQueryService.buildReaderPayloadForCurrentUser(deckId);
    }

    @GetMapping("/{deckId}/reader-window")
    public ReaderPayloadDto readerWindow(
            @PathVariable long deckId,
            @RequestParam(required = false) Integer activeSlideNumber,
            @RequestParam(required = false) Integer radius
    ) {
        return pptDeckQueryService.buildReaderPayloadWindowForCurrentUser(deckId, activeSlideNumber, radius);
    }

    @GetMapping("/{deckId}/reader-position")
    public ReaderPositionDto getReaderPosition(@PathVariable long deckId) {
        pptDeckQueryService.findForCurrentUser(deckId)
                .orElseThrow(() -> new ResourceNotFoundException("PPT deck not found."));
        return pptDeckQueryService.findLastReaderPositionForCurrentUser()
                .orElse(new ReaderPositionDto(null, null));
    }

    @PutMapping("/{deckId}/reader-position")
    public ReaderPositionDto saveReaderPosition(
            @PathVariable long deckId,
            @Valid @RequestBody SaveReaderPositionRequest request
    ) {
        if (deckId != request.deckId()) {
            throw new IllegalArgumentException("Path deckId must match request deckId.");
        }
        return pptReaderCommandService.saveReaderPosition(request);
    }

    @GetMapping("/{deckId}/slides/{slideId}")
    public SlideDto getSlide(@PathVariable long deckId, @PathVariable long slideId) {
        return pptDeckQueryService.findSlideForCurrentUser(deckId, slideId)
                .orElseThrow(() -> new ResourceNotFoundException("PPT slide not found."));
    }

    @GetMapping("/{deckId}/slides/{slideId}/image")
    public ResponseEntity<Resource> slideImage(@PathVariable long deckId, @PathVariable long slideId) {
        PptImageService.ImageResource image = pptImageService.loadSlideImage(deckId, slideId);
        return ResponseEntity.ok()
                .contentType(image.mediaType())
                .body(image.resource());
    }

    @GetMapping("/{deckId}/slides/{slideId}/explanations")
    public List<SlideExplanationDto> listExplanations(@PathVariable long deckId, @PathVariable long slideId) {
        return pptDeckQueryService.listExplanationsForCurrentUser(deckId, slideId);
    }

    @GetMapping("/{deckId}/slides/{slideId}/explanations/latest")
    public SlideExplanationDto latestExplanation(@PathVariable long deckId, @PathVariable long slideId) {
        return pptDeckQueryService.findLatestExplanationForCurrentUser(deckId, slideId)
                .orElseThrow(() -> new ResourceNotFoundException("PPT slide explanation not found."));
    }

    @PostMapping("/{deckId}/slides/{slideId}/explanations")
    @ResponseStatus(HttpStatus.CREATED)
    public SlideExplanationDto addExplanation(
            @PathVariable long deckId,
            @PathVariable long slideId,
            @Valid @RequestBody SaveSlideExplanationRequest request
    ) {
        return pptReaderCommandService.addExplanation(deckId, slideId, request);
    }

    @GetMapping("/{deckId}/slides/{slideId}/questions")
    public List<SlideQuestionDto> listQuestions(@PathVariable long deckId, @PathVariable long slideId) {
        return pptDeckQueryService.listQuestionsForCurrentUser(deckId, slideId);
    }

    @PostMapping("/{deckId}/slides/{slideId}/questions")
    @ResponseStatus(HttpStatus.CREATED)
    public SlideQuestionDto addQuestion(
            @PathVariable long deckId,
            @PathVariable long slideId,
            @Valid @RequestBody SaveSlideQuestionRequest request
    ) {
        return pptReaderCommandService.addQuestion(deckId, slideId, request);
    }
}
