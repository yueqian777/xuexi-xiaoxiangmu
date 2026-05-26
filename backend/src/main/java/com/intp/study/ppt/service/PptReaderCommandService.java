package com.intp.study.ppt.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.ppt.dto.ReaderPositionDto;
import com.intp.study.ppt.dto.SaveReaderPositionRequest;
import com.intp.study.ppt.dto.SaveSlideExplanationRequest;
import com.intp.study.ppt.dto.SaveSlideQuestionRequest;
import com.intp.study.ppt.dto.SlideExplanationDto;
import com.intp.study.ppt.dto.SlideQuestionDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.Objects;

@Service
public class PptReaderCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final PptDeckQueryService pptDeckQueryService;
    private final ObjectMapper objectMapper;

    public PptReaderCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            PptDeckQueryService pptDeckQueryService,
            ObjectMapper objectMapper
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.pptDeckQueryService = pptDeckQueryService;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public ReaderPositionDto saveReaderPosition(SaveReaderPositionRequest request) {
        long userId = currentUserProvider.requireUserId();
        if (pptDeckQueryService.findForCurrentUser(request.deckId()).isEmpty()) {
            throw new ResourceNotFoundException("PPT deck not found.");
        }
        if (request.slideNumber() != null
                && pptDeckQueryService.findSlideByNumberForCurrentUser(request.deckId(), request.slideNumber()).isEmpty()) {
            throw new ResourceNotFoundException("PPT slide not found.");
        }

        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("deck_id", request.deckId());
        if (request.slideNumber() != null && request.slideNumber() > 0) {
            payload.put("slide_number", request.slideNumber());
        }
        jdbcTemplate.update("""
                INSERT INTO app_settings (key, user_id, value, updated_at)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(key) DO UPDATE SET
                    user_id = excluded.user_id,
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """, PptDeckQueryService.readerPositionSettingKey(userId), userId, payload.toString());
        return new ReaderPositionDto(request.deckId(), request.slideNumber());
    }

    @Transactional
    public SlideExplanationDto addExplanation(long deckId, long slideId, SaveSlideExplanationRequest request) {
        long userId = currentUserProvider.requireUserId();
        pptDeckQueryService.ensureSlideBelongsToCurrentUser(deckId, slideId);
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
                    VALUES (?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            ps.setLong(1, userId);
            ps.setLong(2, slideId);
            ps.setString(3, defaultModel(request.model()));
            ps.setString(4, request.explanation());
            return ps;
        }, keyHolder);
        long id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        return findExplanation(userId, id);
    }

    @Transactional
    public SlideQuestionDto addQuestion(long deckId, long slideId, SaveSlideQuestionRequest request) {
        long userId = currentUserProvider.requireUserId();
        pptDeckQueryService.ensureSlideBelongsToCurrentUser(deckId, slideId);
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO slide_questions (user_id, slide_id, question, answer, model, category, sort_order, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            ps.setLong(1, userId);
            ps.setLong(2, slideId);
            ps.setString(3, request.question());
            ps.setString(4, request.answer());
            ps.setString(5, defaultModel(request.model()));
            ps.setString(6, defaultString(request.category()));
            ps.setInt(7, request.sortOrder() == null ? 0 : request.sortOrder());
            ps.setString(8, defaultStatus(request.status()));
            return ps;
        }, keyHolder);
        long id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        return pptDeckQueryService.findQuestionForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("PPT slide question not found."));
    }

    private SlideExplanationDto findExplanation(long userId, long id) {
        return jdbcTemplate.query("""
                SELECT id, slide_id, model, explanation, created_at
                FROM slide_explanations
                WHERE id = ? AND user_id = ?
                """, (rs, rowNum) -> new SlideExplanationDto(
                rs.getLong("id"),
                rs.getLong("slide_id"),
                rs.getString("model"),
                rs.getString("explanation"),
                rs.getString("created_at")
        ), id, userId).stream().findFirst()
                .orElseThrow(() -> new ResourceNotFoundException("PPT slide explanation not found."));
    }

    private String defaultModel(String value) {
        return value == null || value.isBlank() ? "手动编辑" : value;
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    private String defaultStatus(String value) {
        return value == null || value.isBlank() ? "未整理" : value;
    }
}
