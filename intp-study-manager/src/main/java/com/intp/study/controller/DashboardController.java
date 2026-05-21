package com.intp.study.controller;

import com.intp.study.repository.SqlRepository;
import com.intp.study.service.DailyReviewService;
import com.intp.study.service.ReviewTaskService;
import com.intp.study.service.StatsService;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

@Controller
public class DashboardController {
    private final SqlRepository repo;
    private final StatsService statsService;
    private final ReviewTaskService reviewTaskService;
    private final DailyReviewService dailyReviewService;

    public DashboardController(SqlRepository repo, StatsService statsService, ReviewTaskService reviewTaskService, DailyReviewService dailyReviewService) {
        this.repo = repo;
        this.statsService = statsService;
        this.reviewTaskService = reviewTaskService;
        this.dailyReviewService = dailyReviewService;
    }

    @GetMapping({"/", "/dashboard"})
    public String dashboard(Model model) {
        model.addAttribute("title", "首页 Dashboard");
        model.addAttribute("studyCount", statsService.count("study_sessions"));
        model.addAttribute("cardCount", statsService.count("knowledge_cards"));
        model.addAttribute("pendingCount", reviewTaskService.pendingTasks().size());
        model.addAttribute("deckCount", statsService.count("ppt_decks"));
        model.addAttribute("todayTasks", reviewTaskService.todayTasks());
        model.addAttribute("lowMasteryCards", statsService.lowMasteryCards(8));
        model.addAttribute("recentBlockers", statsService.recentBlockers(6));
        model.addAttribute("parkingQuestions", statsService.openParkingQuestions(6));
        model.addAttribute("recentLinks", statsService.recentKnowledgeLinks(6));
        model.addAttribute("dailyPlan", dailyReviewService.getTodayAiReviewPlan());
        model.addAttribute("providers", repo.query("SELECT * FROM api_providers WHERE enabled = 1 ORDER BY id ASC"));
        return "dashboard";
    }
}
