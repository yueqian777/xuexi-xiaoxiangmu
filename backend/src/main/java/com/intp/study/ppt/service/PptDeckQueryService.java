package com.intp.study.ppt.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.ppt.dto.DeckDto;
import com.intp.study.ppt.dto.SectionDto;
import com.intp.study.ppt.dto.SlideDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class PptDeckQueryService {
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
        return jdbcTemplate.query("""
                SELECT ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
                       ps.notes, ps.image_path, ps.section_index, ps.page_type,
                       ps.one_sentence_summary, ps.slide_role, ps.key_points, ps.created_at
                FROM ppt_slides ps
                JOIN ppt_decks pd ON pd.id = ps.deck_id AND pd.user_id = ps.user_id
                WHERE ps.user_id = ? AND ps.deck_id = ?
                ORDER BY ps.slide_number ASC
                """, (rs, rowNum) -> new SlideDto(
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
        ), userId, deckId);
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
}
