package com.intp.study.study.controller;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.study.dto.SaveStudySessionRequest;
import com.intp.study.study.dto.StudySessionDto;
import com.intp.study.study.service.StudySessionCommandService;
import com.intp.study.study.service.StudySessionQueryService;
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
@RequestMapping("/api/study-sessions")
public class StudySessionController {
    private final StudySessionQueryService studySessionQueryService;
    private final StudySessionCommandService studySessionCommandService;

    public StudySessionController(
            StudySessionQueryService studySessionQueryService,
            StudySessionCommandService studySessionCommandService
    ) {
        this.studySessionQueryService = studySessionQueryService;
        this.studySessionCommandService = studySessionCommandService;
    }

    @GetMapping
    public List<StudySessionDto> list() {
        return studySessionQueryService.listForCurrentUser();
    }

    @GetMapping("/{id}")
    public StudySessionDto get(@PathVariable long id) {
        return studySessionQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Study session not found."));
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public StudySessionDto create(@Valid @RequestBody SaveStudySessionRequest request) {
        return studySessionCommandService.create(request);
    }

    @PutMapping("/{id}")
    public StudySessionDto update(@PathVariable long id, @Valid @RequestBody SaveStudySessionRequest request) {
        return studySessionCommandService.update(id, request);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable long id) {
        studySessionCommandService.delete(id);
    }
}
