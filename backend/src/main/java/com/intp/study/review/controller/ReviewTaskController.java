package com.intp.study.review.controller;

import com.intp.study.review.dto.MarkReviewResultRequest;
import com.intp.study.review.dto.ReviewTaskDto;
import com.intp.study.review.service.ReviewTaskCommandService;
import com.intp.study.review.service.ReviewTaskQueryService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/reviews")
public class ReviewTaskController {
    private final ReviewTaskQueryService reviewTaskQueryService;
    private final ReviewTaskCommandService reviewTaskCommandService;

    public ReviewTaskController(
            ReviewTaskQueryService reviewTaskQueryService,
            ReviewTaskCommandService reviewTaskCommandService
    ) {
        this.reviewTaskQueryService = reviewTaskQueryService;
        this.reviewTaskCommandService = reviewTaskCommandService;
    }

    @GetMapping("/tasks")
    public List<ReviewTaskDto> listTasks() {
        return reviewTaskQueryService.listForCurrentUser();
    }

    @GetMapping("/due")
    public List<ReviewTaskDto> listDueTasks() {
        return reviewTaskQueryService.listDueForCurrentUser();
    }

    @PostMapping("/tasks/{taskId}/result")
    public ReviewTaskDto markResult(
            @PathVariable long taskId,
            @Valid @RequestBody MarkReviewResultRequest request
    ) {
        return reviewTaskCommandService.markResult(taskId, request);
    }
}
