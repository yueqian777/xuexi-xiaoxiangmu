package com.intp.study.review.daily.controller;

import com.intp.study.review.daily.dto.DailyAiReviewPlanDto;
import com.intp.study.review.daily.dto.DailyReviewLogDto;
import com.intp.study.review.daily.service.DailyReviewQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/reviews")
public class DailyReviewController {
    private final DailyReviewQueryService dailyReviewQueryService;

    public DailyReviewController(DailyReviewQueryService dailyReviewQueryService) {
        this.dailyReviewQueryService = dailyReviewQueryService;
    }

    @GetMapping("/daily-log")
    public List<DailyReviewLogDto> listDailyLogs() {
        return dailyReviewQueryService.listLogsForCurrentUser();
    }

    @GetMapping("/ai-plan")
    public List<DailyAiReviewPlanDto> listAiPlans() {
        return dailyReviewQueryService.listAiPlansForCurrentUser();
    }
}
