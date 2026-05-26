package com.intp.study.ppt.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.ppt.dto.DeckDto;
import com.intp.study.ppt.dto.ReaderPayloadDto;
import com.intp.study.ppt.dto.ReaderPositionDto;
import com.intp.study.ppt.dto.ReaderSlideDto;
import com.intp.study.ppt.dto.SectionDto;
import com.intp.study.ppt.dto.SlideExplanationDto;
import com.intp.study.ppt.dto.SlideDto;
import com.intp.study.ppt.dto.SlideQuestionDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.Comparator;
import java.util.HashMap;
import java.util.Map;
import java.util.List;
import java.util.Optional;

@Service
public class PptDeckQueryService {
    private static final String LAST_READER_POSITION_SETTING_KEY = "ppt_reader_last_position";

    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public PptDeckQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<DeckDto> listForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT id, filename, title, subject, category, sort_order, status,
                       slide_count, outline, outline_generated_at, created_at
                FROM ppt_decks
                WHERE user_id = ?
                ORDER BY status ASC, category ASC, sort_order ASC, created_at DESC, id DESC
                """, (rs, rowNum) -> new DeckDto(
                rs.getLong("id"),
                rs.getString("filename"),
                rs.getString("title"),
                rs.getString("subject"),
                rs.getString("category"),
                rs.getInt("sort_order"),
                rs.getString("status"),
                rs.getInt("slide_count"),
                rs.getString("outline"),
                rs.getString("outline_generated_at"),
                rs.getString("created_at")
        ), userId);
    }

    public Optional<DeckDto> findForCurrentUser(long deckId) {
        long userId = currentUserProvider.requireUserId();
        return findForUser(userId, deckId);
    }

    public Optional<SlideDto> findSlideForCurrentUser(long deckId, long slideId) {
        long userId = currentUserProvider.requireUserId();
        return querySlides("""
                SELECT ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
                       ps.notes, ps.image_path, ps.section_index, ps.page_type,
                       ps.one_sentence_summary, ps.slide_role, ps.key_points, ps.created_at
                FROM ppt_slides ps
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE ps.user_id = ? AND ps.deck_id = ? AND ps.id = ?
                """, userId, deckId, slideId).stream().findFirst();
    }

    public Optional<SlideDto> findSlideByNumberForCurrentUser(long deckId, int slideNumber) {
        long userId = currentUserProvider.requireUserId();
        return querySlides("""
                SELECT ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
                       ps.notes, ps.image_path, ps.section_index, ps.page_type,
                       ps.one_sentence_summary, ps.slide_role, ps.key_points, ps.created_at
                FROM ppt_slides ps
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE ps.user_id = ? AND ps.deck_id = ? AND ps.slide_number = ?
                """, userId, deckId, slideNumber).stream().findFirst();
    }

    public Optional<SlideExplanationDto> findLatestExplanationForCurrentUser(long deckId, long slideId) {
        long userId = currentUserProvider.requireUserId();
        ensureSlideBelongsToUser(userId, deckId, slideId);
        return queryExplanations("""
                SELECT se.id, se.slide_id, se.model, se.explanation, se.created_at
                FROM slide_explanations se
                JOIN ppt_slides ps ON ps.id = se.slide_id AND ps.user_id = se.user_id
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE se.user_id = ? AND ps.deck_id = ? AND se.slide_id = ?
                ORDER BY se.created_at DESC, se.id DESC
                LIMIT 1
                """, userId, deckId, slideId).stream().findFirst();
    }

    public List<SlideExplanationDto> listExplanationsForCurrentUser(long deckId, long slideId) {
        long userId = currentUserProvider.requireUserId();
        ensureSlideBelongsToUser(userId, deckId, slideId);
        return queryExplanations("""
                SELECT se.id, se.slide_id, se.model, se.explanation, se.created_at
                FROM slide_explanations se
                JOIN ppt_slides ps ON ps.id = se.slide_id AND ps.user_id = se.user_id
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE se.user_id = ? AND ps.deck_id = ? AND se.slide_id = ?
                ORDER BY se.created_at DESC, se.id DESC
                """, userId, deckId, slideId);
    }

    public List<SlideQuestionDto> listQuestionsForCurrentUser(long deckId, long slideId) {
        long userId = currentUserProvider.requireUserId();
        ensureSlideBelongsToUser(userId, deckId, slideId);
        return jdbcTemplate.query("""
                SELECT sq.id, sq.slide_id, sq.question, sq.answer, sq.model,
                       sq.category, sq.sort_order, sq.status, sq.created_at
                FROM slide_questions sq
                JOIN ppt_slides ps ON ps.id = sq.slide_id AND ps.user_id = sq.user_id
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE sq.user_id = ? AND ps.deck_id = ? AND sq.slide_id = ?
                ORDER BY sq.sort_order ASC, sq.created_at ASC, sq.id ASC
                """, (rs, rowNum) -> new SlideQuestionDto(
                rs.getLong("id"),
                rs.getLong("slide_id"),
                rs.getString("question"),
                rs.getString("answer"),
                rs.getString("model"),
                rs.getString("category"),
                rs.getInt("sort_order"),
                rs.getString("status"),
                rs.getString("created_at")
        ), userId, deckId, slideId);
    }

    public Optional<SlideQuestionDto> findQuestionForCurrentUser(long questionId) {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT sq.id, sq.slide_id, sq.question, sq.answer, sq.model,
                       sq.category, sq.sort_order, sq.status, sq.created_at
                FROM slide_questions sq
                JOIN ppt_slides ps ON ps.id = sq.slide_id AND ps.user_id = sq.user_id
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE sq.user_id = ? AND sq.id = ?
                """, (rs, rowNum) -> new SlideQuestionDto(
                rs.getLong("id"),
                rs.getLong("slide_id"),
                rs.getString("question"),
                rs.getString("answer"),
                rs.getString("model"),
                rs.getString("category"),
                rs.getInt("sort_order"),
                rs.getString("status"),
                rs.getString("created_at")
        ), userId, questionId).stream().findFirst();
    }

    public Optional<ReaderPositionDto> findLastReaderPositionForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        List<ReaderPositionDto> positions = jdbcTemplate.query("""
                SELECT value
                FROM app_settings
                WHERE key = ?
                """, (rs, rowNum) -> parseReaderPosition(rs.getString("value")), readerPositionSettingKey(userId));
        return positions.stream()
                .filter(position -> position.deckId() != null)
                .findFirst();
    }

    public ReaderPayloadDto buildReaderPayloadForCurrentUser(long deckId) {
        DeckDto deck = findForCurrentUser(deckId)
                .orElseThrow(() -> new com.intp.study.common.error.ResourceNotFoundException("PPT deck not found."));
        List<SlideDto> slides = listSlidesForCurrentUser(deckId);
        return buildReaderPayload(deck, slides);
    }

    public ReaderPayloadDto buildReaderPayloadWindowForCurrentUser(long deckId, Integer activeSlideNumber, Integer radius) {
        DeckDto deck = findForCurrentUser(deckId)
                .orElseThrow(() -> new com.intp.study.common.error.ResourceNotFoundException("PPT deck not found."));
        ReaderPositionDto lastPosition = findLastReaderPositionForCurrentUser()
                .orElse(new ReaderPositionDto(null, null));
        int center = activeSlideNumber == null || activeSlideNumber <= 0
                ? (lastPosition.slideNumber() == null ? 1 : lastPosition.slideNumber())
                : activeSlideNumber;
        int safeRadius = radius == null ? 2 : Math.max(0, Math.min(radius, 10));
        long userId = currentUserProvider.requireUserId();
        List<SlideDto> slides = querySlides("""
                SELECT ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
                       ps.notes, ps.image_path, ps.section_index, ps.page_type,
                       ps.one_sentence_summary, ps.slide_role, ps.key_points, ps.created_at
                FROM ppt_slides ps
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE ps.user_id = ? AND ps.deck_id = ?
                  AND ps.slide_number BETWEEN ? AND ?
                ORDER BY ps.slide_number ASC
                """, userId, deckId, Math.max(1, center - safeRadius), center + safeRadius);
        if (slides.isEmpty()) {
            slides = querySlides("""
                    SELECT ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
                           ps.notes, ps.image_path, ps.section_index, ps.page_type,
                           ps.one_sentence_summary, ps.slide_role, ps.key_points, ps.created_at
                    FROM ppt_slides ps
                    JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                    WHERE ps.user_id = ? AND ps.deck_id = ?
                    ORDER BY ps.slide_number ASC
                    LIMIT ?
                    """, userId, deckId, Math.max(1, safeRadius * 2 + 1));
        }
        return buildReaderPayload(deck, slides);
    }

    private ReaderPayloadDto buildReaderPayload(DeckDto deck, List<SlideDto> slides) {
        long deckId = deck.id();
        List<SectionDto> sections = listSectionsForCurrentUser(deckId);
        ReaderPositionDto lastPosition = findLastReaderPositionForCurrentUser()
                .orElse(new ReaderPositionDto(null, null));
        int initialSlideNumber = initialReaderSlideNumber(deckId, slides, lastPosition);
        Map<Long, SlideExplanationDto> latestExplanations = latestExplanationsBySlideIds(userId(), slides.stream()
                .map(SlideDto::id)
                .toList());
        Map<Long, List<SlideQuestionDto>> questions = questionsBySlideIds(userId(), slides.stream()
                .map(SlideDto::id)
                .toList());
        List<ReaderSlideDto> readerSlides = slides.stream()
                .map(slide -> new ReaderSlideDto(
                        slide,
                        latestExplanations.get(slide.id()),
                        questions.getOrDefault(slide.id(), List.of()),
                        "/api/ppt/decks/" + deckId + "/slides/" + slide.id() + "/image",
                        slide.imagePath() != null && !slide.imagePath().isBlank()
                ))
                .toList();
        return new ReaderPayloadDto(deck, readerSlides, sections, lastPosition, initialSlideNumber);
    }

    boolean slideBelongsToCurrentUser(long deckId, long slideId) {
        long userId = currentUserProvider.requireUserId();
        return slideBelongsToUser(userId, deckId, slideId);
    }

    void ensureSlideBelongsToCurrentUser(long deckId, long slideId) {
        long userId = currentUserProvider.requireUserId();
        ensureSlideBelongsToUser(userId, deckId, slideId);
    }

    private Optional<DeckDto> findForUser(long userId, long deckId) {
        List<DeckDto> decks = jdbcTemplate.query("""
                SELECT id, filename, title, subject, category, sort_order, status,
                       slide_count, outline, outline_generated_at, created_at
                FROM ppt_decks
                WHERE user_id = ? AND id = ?
                """, (rs, rowNum) -> new DeckDto(
                rs.getLong("id"),
                rs.getString("filename"),
                rs.getString("title"),
                rs.getString("subject"),
                rs.getString("category"),
                rs.getInt("sort_order"),
                rs.getString("status"),
                rs.getInt("slide_count"),
                rs.getString("outline"),
                rs.getString("outline_generated_at"),
                rs.getString("created_at")
        ), userId, deckId);
        return decks.stream().findFirst();
    }

    public List<SlideDto> listSlidesForCurrentUser(long deckId) {
        long userId = currentUserProvider.requireUserId();
        return querySlides("""
                SELECT ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
                       ps.notes, ps.image_path, ps.section_index, ps.page_type,
                       ps.one_sentence_summary, ps.slide_role, ps.key_points, ps.created_at
                FROM ppt_slides ps
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE ps.user_id = ? AND ps.deck_id = ?
                ORDER BY ps.slide_number ASC
                """, userId, deckId);
    }

    public List<SectionDto> listSectionsForCurrentUser(long deckId) {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT ps.id, ps.deck_id, ps.section_index, ps.title, ps.topic,
                       ps.core_question, ps.summary, ps.key_terms_json,
                       ps.prerequisite_concepts_json, ps.start_slide, ps.end_slide,
                       ps.created_at, ps.updated_at
                FROM ppt_sections ps
                JOIN ppt_decks pd ON pd.id = ps.deck_id
                WHERE pd.user_id = ? AND ps.deck_id = ?
                ORDER BY ps.section_index ASC
                """, (rs, rowNum) -> new SectionDto(
                rs.getLong("id"),
                rs.getLong("deck_id"),
                rs.getInt("section_index"),
                rs.getString("title"),
                rs.getString("topic"),
                rs.getString("core_question"),
                rs.getString("summary"),
                rs.getString("key_terms_json"),
                rs.getString("prerequisite_concepts_json"),
                rs.getInt("start_slide"),
                rs.getInt("end_slide"),
                rs.getString("created_at"),
                rs.getString("updated_at")
        ), userId, deckId);
    }

    private List<SlideDto> querySlides(String sql, Object... args) {
        return jdbcTemplate.query(sql, (rs, rowNum) -> new SlideDto(
                rs.getLong("id"),
                rs.getLong("deck_id"),
                rs.getInt("slide_number"),
                rs.getString("title"),
                rs.getString("slide_text"),
                rs.getString("notes"),
                rs.getString("image_path"),
                rs.getInt("section_index"),
                rs.getString("page_type"),
                rs.getString("one_sentence_summary"),
                rs.getString("slide_role"),
                rs.getString("key_points"),
                rs.getString("created_at")
        ), args);
    }

    private List<SlideExplanationDto> queryExplanations(String sql, Object... args) {
        return jdbcTemplate.query(sql, (rs, rowNum) -> new SlideExplanationDto(
                rs.getLong("id"),
                rs.getLong("slide_id"),
                rs.getString("model"),
                rs.getString("explanation"),
                rs.getString("created_at")
        ), args);
    }

    private boolean slideBelongsToUser(long userId, long deckId, long slideId) {
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM ppt_slides ps
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE ps.user_id = ? AND ps.deck_id = ? AND ps.id = ?
                """, Integer.class, userId, deckId, slideId);
        return count != null && count > 0;
    }

    private void ensureSlideBelongsToUser(long userId, long deckId, long slideId) {
        if (!slideBelongsToUser(userId, deckId, slideId)) {
            throw new com.intp.study.common.error.ResourceNotFoundException("PPT slide not found.");
        }
    }

    static String readerPositionSettingKey(long userId) {
        return "user:" + userId + ":" + LAST_READER_POSITION_SETTING_KEY;
    }

    private ReaderPositionDto parseReaderPosition(String rawValue) {
        if (rawValue == null || rawValue.isBlank()) {
            return new ReaderPositionDto(null, null);
        }
        try {
            com.fasterxml.jackson.databind.JsonNode node = new com.fasterxml.jackson.databind.ObjectMapper().readTree(rawValue);
            Long deckId = positiveLong(node.get("deck_id"));
            Integer slideNumber = positiveInt(node.get("slide_number"));
            return new ReaderPositionDto(deckId, slideNumber);
        } catch (Exception ignored) {
            return new ReaderPositionDto(null, null);
        }
    }

    private Long positiveLong(com.fasterxml.jackson.databind.JsonNode node) {
        if (node == null || !node.canConvertToLong()) {
            return null;
        }
        long value = node.asLong();
        return value > 0 ? value : null;
    }

    private Integer positiveInt(com.fasterxml.jackson.databind.JsonNode node) {
        if (node == null || !node.canConvertToInt()) {
            return null;
        }
        int value = node.asInt();
        return value > 0 ? value : null;
    }

    private int initialReaderSlideNumber(long deckId, List<SlideDto> slides, ReaderPositionDto lastPosition) {
        if (slides.isEmpty()) {
            return 1;
        }
        if (lastPosition.deckId() != null
                && lastPosition.deckId() == deckId
                && lastPosition.slideNumber() != null
                && slides.stream().anyMatch(slide -> slide.slideNumber() == lastPosition.slideNumber())) {
            return lastPosition.slideNumber();
        }
        return slides.stream()
                .min(Comparator.comparingInt(SlideDto::slideNumber))
                .map(SlideDto::slideNumber)
                .orElse(1);
    }

    private long userId() {
        return currentUserProvider.requireUserId();
    }

    private Map<Long, SlideExplanationDto> latestExplanationsBySlideIds(long userId, List<Long> slideIds) {
        if (slideIds.isEmpty()) {
            return Map.of();
        }
        String placeholders = String.join(",", java.util.Collections.nCopies(slideIds.size(), "?"));
        Object[] args = new Object[slideIds.size() + 1];
        args[0] = userId;
        for (int i = 0; i < slideIds.size(); i++) {
            args[i + 1] = slideIds.get(i);
        }
        List<SlideExplanationDto> rows = queryExplanations("""
                SELECT id, slide_id, model, explanation, created_at
                FROM (
                    SELECT se.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY se.slide_id
                               ORDER BY se.created_at DESC, se.id DESC
                           ) AS rn
                    FROM slide_explanations se
                    WHERE se.user_id = ? AND se.slide_id IN (%s)
                )
                WHERE rn = 1
                """.formatted(placeholders), args);
        Map<Long, SlideExplanationDto> result = new HashMap<>();
        for (SlideExplanationDto row : rows) {
            result.put(row.slideId(), row);
        }
        return result;
    }

    private Map<Long, List<SlideQuestionDto>> questionsBySlideIds(long userId, List<Long> slideIds) {
        if (slideIds.isEmpty()) {
            return Map.of();
        }
        String placeholders = String.join(",", java.util.Collections.nCopies(slideIds.size(), "?"));
        Object[] args = new Object[slideIds.size() + 1];
        args[0] = userId;
        for (int i = 0; i < slideIds.size(); i++) {
            args[i + 1] = slideIds.get(i);
        }
        List<SlideQuestionDto> rows = jdbcTemplate.query("""
                SELECT slide_id, id, question, answer, model, category, sort_order, status, created_at
                FROM slide_questions
                WHERE user_id = ? AND slide_id IN (%s)
                ORDER BY slide_id ASC, sort_order ASC, created_at ASC, id ASC
                """.formatted(placeholders), (rs, rowNum) -> new SlideQuestionDto(
                rs.getLong("id"),
                rs.getLong("slide_id"),
                rs.getString("question"),
                rs.getString("answer"),
                rs.getString("model"),
                rs.getString("category"),
                rs.getInt("sort_order"),
                rs.getString("status"),
                rs.getString("created_at")
        ), args);
        Map<Long, List<SlideQuestionDto>> result = new HashMap<>();
        for (SlideQuestionDto row : rows) {
            result.computeIfAbsent(row.slideId(), ignored -> new java.util.ArrayList<>()).add(row);
        }
        return result;
    }
}
