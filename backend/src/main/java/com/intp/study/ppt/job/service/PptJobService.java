package com.intp.study.ppt.job.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.ppt.job.dto.PptJobDto;
import com.intp.study.ppt.job.dto.StartPptJobRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class PptJobService {
    private final CurrentUserProvider currentUserProvider;
    private final JdbcTemplate jdbcTemplate;

    public PptJobService(CurrentUserProvider currentUserProvider, JdbcTemplate jdbcTemplate) {
        this.currentUserProvider = currentUserProvider;
        this.jdbcTemplate = jdbcTemplate;
    }

    public PptJobDto start(long deckId, StartPptJobRequest request) {
        long userId = currentUserProvider.requireUserId();
        ensureDeck(userId, deckId);
        String id = UUID.randomUUID().toString();
        String type = request == null || request.jobType() == null || request.jobType().isBlank()
                ? "parse_document"
                : request.jobType();
        jdbcTemplate.update("""
                INSERT INTO ppt_jobs (id, user_id, deck_id, job_type, status, progress, status_text)
                VALUES (?, ?, ?, ?, 'queued', 0, ?)
                """, id, userId, deckId, type, "任务已创建，等待后台 worker 接入。");
        return get(id);
    }

    public PptJobDto get(String jobId) {
        long userId = currentUserProvider.requireUserId();
        return query("""
                SELECT id, deck_id, job_type, status, progress, status_text, stop_requested, created_at, updated_at
                FROM ppt_jobs
                WHERE id = ? AND user_id = ?
                """, jobId, userId).stream().findFirst()
                .orElseThrow(() -> new ResourceNotFoundException("PPT job not found."));
    }

    public List<PptJobDto> list() {
        long userId = currentUserProvider.requireUserId();
        return query("""
                SELECT id, deck_id, job_type, status, progress, status_text, stop_requested, created_at, updated_at
                FROM ppt_jobs
                WHERE user_id = ?
                ORDER BY created_at DESC
                """, userId);
    }

    public PptJobDto stop(String jobId) {
        long userId = currentUserProvider.requireUserId();
        int updated = jdbcTemplate.update("""
                UPDATE ppt_jobs
                SET stop_requested = 1,
                    status = CASE WHEN status IN ('succeeded', 'failed') THEN status ELSE 'cancelled' END,
                    status_text = CASE WHEN status IN ('succeeded', 'failed') THEN status_text ELSE '任务已请求停止。' END,
                    updated_at = datetime('now', 'localtime'),
                    finished_at = CASE WHEN status IN ('succeeded', 'failed') THEN finished_at ELSE datetime('now', 'localtime') END
                WHERE id = ? AND user_id = ?
                """, jobId, userId);
        if (updated == 0) {
            throw new ResourceNotFoundException("PPT job not found.");
        }
        return get(jobId);
    }

    private void ensureDeck(long userId, long deckId) {
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM ppt_decks
                WHERE id = ? AND user_id = ?
                """, Integer.class, deckId, userId);
        if (count == null || count == 0) {
            throw new ResourceNotFoundException("PPT deck not found.");
        }
    }

    private List<PptJobDto> query(String sql, Object... args) {
        return jdbcTemplate.query(sql, (rs, rowNum) -> new PptJobDto(
                rs.getString("id"),
                rs.getLong("deck_id"),
                rs.getString("job_type"),
                rs.getString("status"),
                rs.getInt("progress"),
                rs.getString("status_text"),
                rs.getInt("stop_requested") != 0,
                rs.getString("created_at"),
                rs.getString("updated_at")
        ), args);
    }

    private String now() {
        return LocalDateTime.now().withNano(0).toString();
    }

}
