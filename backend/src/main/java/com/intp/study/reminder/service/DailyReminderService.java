package com.intp.study.reminder.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.reminder.dto.DailyReminderConfigDto;
import com.intp.study.reminder.dto.DailyReminderStatusDto;
import com.intp.study.reminder.dto.MarkDailyReviewDoneRequest;
import com.intp.study.reminder.dto.SaveDailyReminderConfigRequest;
import com.intp.study.review.daily.dto.DailyReviewLogDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Optional;

@Service
public class DailyReminderService {
    private static final String SETTING_KEY = "daily_review_reminder";
    private static final DailyReminderConfigDto DEFAULT_CONFIG = new DailyReminderConfigDto(true, "21:00");

    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final ObjectMapper objectMapper;

    public DailyReminderService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            ObjectMapper objectMapper
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.objectMapper = objectMapper;
    }

    public DailyReminderStatusDto getStatus() {
        DailyReminderConfigDto config = getConfig();
        DailyReviewLogDto todayLog = getTodayReviewLog().orElse(null);
        return new DailyReminderStatusDto(config, todayLog, isDueNow(config, todayLog));
    }

    public DailyReminderConfigDto getConfig() {
        long userId = currentUserProvider.requireUserId();
        List<String> values = jdbcTemplate.query("""
                SELECT value
                FROM app_settings
                WHERE key = ?
                """, (rs, rowNum) -> rs.getString("value"), userSettingKey(userId));
        if (values.isEmpty()) {
            return DEFAULT_CONFIG;
        }
        return parseConfig(values.getFirst());
    }

    @Transactional
    public DailyReminderConfigDto saveConfig(SaveDailyReminderConfigRequest request) {
        long userId = currentUserProvider.requireUserId();
        DailyReminderConfigDto config = new DailyReminderConfigDto(
                request.enabled() == null || request.enabled(),
                normalizeTime(request.time())
        );
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("enabled", config.enabled());
        payload.put("time", config.time());
        jdbcTemplate.update("""
                INSERT INTO app_settings (key, user_id, value, updated_at)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(key) DO UPDATE SET
                    user_id = excluded.user_id,
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """, userSettingKey(userId), userId, payload.toString());
        return config;
    }

    public Optional<DailyReviewLogDto> getTodayReviewLog() {
        long userId = currentUserProvider.requireUserId();
        return queryTodayLog(userId).stream().findFirst();
    }

    @Transactional
    public DailyReviewLogDto markTodayDone(MarkDailyReviewDoneRequest request) {
        long userId = currentUserProvider.requireUserId();
        String today = LocalDate.now().toString();
        String notes = request == null || request.notes() == null ? "" : request.notes();
        List<Long> existing = jdbcTemplate.query("""
                SELECT id
                FROM daily_review_logs
                WHERE user_id = ? AND review_date = ?
                """, (rs, rowNum) -> rs.getLong("id"), userId, today);
        if (existing.isEmpty()) {
            jdbcTemplate.update("""
                    INSERT INTO daily_review_logs (user_id, review_date, status, notes)
                    VALUES (?, ?, '已完成', ?)
                    """, userId, today, notes);
        } else {
            jdbcTemplate.update("""
                    UPDATE daily_review_logs
                    SET status = '已完成', notes = ?, created_at = datetime('now', 'localtime')
                    WHERE user_id = ? AND review_date = ?
                    """, notes, userId, today);
        }
        return getTodayReviewLog()
                .orElseThrow(() -> new IllegalStateException("Daily review log was not saved."));
    }

    private boolean isDueNow(DailyReminderConfigDto config, DailyReviewLogDto todayLog) {
        if (!config.enabled() || todayLog != null) {
            return false;
        }
        return !LocalTime.now().isBefore(LocalTime.parse(config.time(), DateTimeFormatter.ofPattern("HH:mm")));
    }

    private List<DailyReviewLogDto> queryTodayLog(long userId) {
        return jdbcTemplate.query("""
                SELECT id, review_date, status, notes, created_at
                FROM daily_review_logs
                WHERE user_id = ? AND review_date = ?
                """, (rs, rowNum) -> new DailyReviewLogDto(
                rs.getLong("id"),
                rs.getString("review_date"),
                rs.getString("status"),
                rs.getString("notes"),
                rs.getString("created_at")
        ), userId, LocalDate.now().toString());
    }

    private DailyReminderConfigDto parseConfig(String rawValue) {
        try {
            JsonNode node = objectMapper.readTree(rawValue);
            boolean enabled = node.has("enabled") ? node.get("enabled").asBoolean(DEFAULT_CONFIG.enabled()) : DEFAULT_CONFIG.enabled();
            String time = normalizeTime(node.has("time") ? node.get("time").asText() : DEFAULT_CONFIG.time());
            return new DailyReminderConfigDto(enabled, time);
        } catch (Exception ignored) {
            return DEFAULT_CONFIG;
        }
    }

    private String normalizeTime(String value) {
        if (value == null || value.isBlank()) {
            return DEFAULT_CONFIG.time();
        }
        try {
            return LocalTime.parse(value, DateTimeFormatter.ofPattern("HH:mm"))
                    .format(DateTimeFormatter.ofPattern("HH:mm"));
        } catch (Exception ignored) {
            return DEFAULT_CONFIG.time();
        }
    }

    private String userSettingKey(long userId) {
        return "user:" + userId + ":" + SETTING_KEY;
    }
}
