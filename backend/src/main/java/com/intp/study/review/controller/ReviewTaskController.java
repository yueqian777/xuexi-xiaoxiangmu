package com.intp.study.review.controller;

import com.intp.study.review.dto.ReviewTaskDto;
import com.intp.study.review.service.ReviewTaskQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/reviews")
public class ReviewTaskController {
    private final ReviewTaskQueryService reviewTaskQueryService;

    public ReviewTaskController(ReviewTaskQueryService reviewTaskQueryService) {
        this.reviewTaskQueryService = reviewTaskQueryService;
    }

    @GetMapping("/tasks")
    public List<ReviewTaskDto> listTasks() {
        return reviewTaskQueryService.listForCurrentUser();
    }

    @GetMapping("/due")
    public List<ReviewTaskDto> listDueTasks() {
        return reviewTaskQueryService.listDueForCurrentUser();
    }
}
