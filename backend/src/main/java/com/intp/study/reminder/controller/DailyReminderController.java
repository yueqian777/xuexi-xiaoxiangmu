package com.intp.study.reminder.controller;

import com.intp.study.reminder.dto.DailyReminderConfigDto;
import com.intp.study.reminder.dto.DailyReminderStatusDto;
import com.intp.study.reminder.dto.MarkDailyReviewDoneRequest;
import com.intp.study.reminder.dto.SaveDailyReminderConfigRequest;
import com.intp.study.reminder.service.DailyReminderService;
import com.intp.study.review.daily.dto.DailyReviewLogDto;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/reminders/daily-review")
public class DailyReminderController {
    private final DailyReminderService dailyReminderService;

    public DailyReminderController(DailyReminderService dailyReminderService) {
        this.dailyReminderService = dailyReminderService;
    }

    @GetMapping
    public DailyReminderStatusDto status() {
        return dailyReminderService.getStatus();
    }

    @PutMapping
    public DailyReminderConfigDto saveConfig(@Valid @RequestBody SaveDailyReminderConfigRequest request) {
        return dailyReminderService.saveConfig(request);
    }

    @PostMapping("/done")
    public DailyReviewLogDto markTodayDone(@RequestBody MarkDailyReviewDoneRequest request) {
        return dailyReminderService.markTodayDone(request);
    }
}
