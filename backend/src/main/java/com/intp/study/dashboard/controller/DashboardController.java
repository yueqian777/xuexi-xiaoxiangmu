package com.intp.study.dashboard.controller;

import com.intp.study.dashboard.dto.DashboardSummaryDto;
import com.intp.study.dashboard.service.DashboardQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/dashboard")
public class DashboardController {
    private final DashboardQueryService dashboardQueryService;

    public DashboardController(DashboardQueryService dashboardQueryService) {
        this.dashboardQueryService = dashboardQueryService;
    }

    @GetMapping("/summary")
    public DashboardSummaryDto summary() {
        return dashboardQueryService.summary();
    }
}
