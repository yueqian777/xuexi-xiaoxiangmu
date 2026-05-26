package com.intp.study.mainline.controller;

import com.intp.study.mainline.dto.BranchQuestionDto;
import com.intp.study.mainline.dto.MainlineAnchorDto;
import com.intp.study.mainline.dto.SaveBranchQuestionRequest;
import com.intp.study.mainline.dto.SaveMainlineAnchorRequest;
import com.intp.study.mainline.service.MainlineCommandService;
import com.intp.study.mainline.service.MainlineAnchorQueryService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/mainline/anchors")
public class MainlineAnchorController {
    private final MainlineAnchorQueryService mainlineAnchorQueryService;
    private final MainlineCommandService mainlineCommandService;

    public MainlineAnchorController(
            MainlineAnchorQueryService mainlineAnchorQueryService,
            MainlineCommandService mainlineCommandService
    ) {
        this.mainlineAnchorQueryService = mainlineAnchorQueryService;
        this.mainlineCommandService = mainlineCommandService;
    }

    @GetMapping
    public List<MainlineAnchorDto> list() {
        return mainlineAnchorQueryService.listForCurrentUser();
    }

    @GetMapping("/by-session/{sessionId}")
    public List<MainlineAnchorDto> listBySession(@PathVariable long sessionId) {
        return mainlineAnchorQueryService.listForSession(sessionId);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public MainlineAnchorDto createAnchor(@Valid @RequestBody SaveMainlineAnchorRequest request) {
        return mainlineCommandService.createAnchor(request);
    }

    @GetMapping("/branches/by-session/{sessionId}")
    public List<BranchQuestionDto> listBranchQuestionsBySession(@PathVariable long sessionId) {
        return mainlineAnchorQueryService.listBranchQuestionsForSession(sessionId);
    }

    @PostMapping("/branches")
    @ResponseStatus(HttpStatus.CREATED)
    public BranchQuestionDto createBranchQuestion(@Valid @RequestBody SaveBranchQuestionRequest request) {
        return mainlineCommandService.createBranchQuestion(request);
    }
}
