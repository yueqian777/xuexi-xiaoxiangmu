package com.intp.study.review.daily.controller;

import com.fasterxml.jackson.databind.node.ObjectNode;
import com.intp.study.review.daily.dto.DailyAiReviewPlanDto;
import com.intp.study.review.daily.dto.DailyReviewLogDto;
import com.intp.study.review.daily.dto.EvaluateDailyAiReviewRequest;
import com.intp.study.review.daily.dto.GenerateDailyAiReviewRequest;
import com.intp.study.review.daily.service.DailyAiReviewCommandService;
import com.intp.study.review.daily.service.DailyReviewQueryService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/reviews")
public class DailyReviewController {
    private final DailyReviewQueryService dailyReviewQueryService;
    private final DailyAiReviewCommandService dailyAiReviewCommandService;

    public DailyReviewController(
            DailyReviewQueryService dailyReviewQueryService,
            DailyAiReviewCommandService dailyAiReviewCommandService
    ) {
        this.dailyReviewQueryService = dailyReviewQueryService;
        this.dailyAiReviewCommandService = dailyAiReviewCommandService;
    }

    @GetMapping("/daily-log")
    public List<DailyReviewLogDto> listDailyLogs() {
        return dailyReviewQueryService.listLogsForCurrentUser();
    }

    @GetMapping("/ai-plan")
    public List<DailyAiReviewPlanDto> listAiPlans() {
        return dailyReviewQueryService.listAiPlansForCurrentUser();
    }

    @GetMapping("/ai-plan/today")
    public DailyAiReviewPlanDto getTodayAiPlan() {
        return dailyReviewQueryService.findTodayAiPlanForCurrentUser()
                .orElseThrow(() -> new com.intp.study.common.error.ResourceNotFoundException("Daily AI review plan not found."));
    }

    @PostMapping("/ai-plan")
    public DailyAiReviewPlanDto generateTodayAiPlan(@Valid @RequestBody GenerateDailyAiReviewRequest request) {
        return dailyAiReviewCommandService.generateTodayPlan(request);
    }

    @PostMapping("/ai-plan/evaluate")
    public ObjectNode evaluateTodayAiPlan(@Valid @RequestBody EvaluateDailyAiReviewRequest request) {
        return dailyAiReviewCommandService.evaluateTodayPlan(request);
    }
}
