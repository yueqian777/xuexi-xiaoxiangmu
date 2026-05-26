package com.intp.study.ppt.job.controller;

import com.intp.study.ppt.job.dto.PptJobDto;
import com.intp.study.ppt.job.dto.StartPptJobRequest;
import com.intp.study.ppt.job.service.PptJobService;
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
@RequestMapping("/api/ppt")
public class PptJobController {
    private final PptJobService pptJobService;

    public PptJobController(PptJobService pptJobService) {
        this.pptJobService = pptJobService;
    }

    @PostMapping("/decks/{deckId}/jobs")
    @ResponseStatus(HttpStatus.CREATED)
    public PptJobDto start(@PathVariable long deckId, @RequestBody(required = false) StartPptJobRequest request) {
        return pptJobService.start(deckId, request);
    }

    @GetMapping("/jobs")
    public List<PptJobDto> list() {
        return pptJobService.list();
    }

    @GetMapping("/jobs/{jobId}")
    public PptJobDto get(@PathVariable String jobId) {
        return pptJobService.get(jobId);
    }

    @PostMapping("/jobs/{jobId}/stop")
    public PptJobDto stop(@PathVariable String jobId) {
        return pptJobService.stop(jobId);
    }
}
