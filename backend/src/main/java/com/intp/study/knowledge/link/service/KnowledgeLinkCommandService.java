package com.intp.study.knowledge.link.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.knowledge.link.dto.KnowledgeLinkDto;
import com.intp.study.knowledge.link.dto.SaveKnowledgeLinkRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.List;
import java.util.Objects;

@Service
public class KnowledgeLinkCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final KnowledgeLinkQueryService knowledgeLinkQueryService;

    public KnowledgeLinkCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            KnowledgeLinkQueryService knowledgeLinkQueryService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.knowledgeLinkQueryService = knowledgeLinkQueryService;
    }

    @Transactional
    public KnowledgeLinkDto upsert(SaveKnowledgeLinkRequest request) {
        long userId = currentUserProvider.requireUserId();
        long sourceId = request.sourceKnowledgeId();
        long targetId = request.targetKnowledgeId();
        if (sourceId == targetId) {
            throw new IllegalArgumentException("sourceKnowledgeId and targetKnowledgeId must be different.");
        }
        ensureCardBelongsToUser(userId, sourceId);
        ensureCardBelongsToUser(userId, targetId);

        String relationType = defaultRelationType(request.relationType());
        List<Long> existing = jdbcTemplate.query("""
                SELECT id
                FROM knowledge_links
                WHERE user_id = ? AND source_knowledge_id = ? AND target_knowledge_id = ? AND relation_type = ?
                """, (rs, rowNum) -> rs.getLong("id"), userId, sourceId, targetId, relationType);
        long id;
        if (existing.isEmpty()) {
            KeyHolder keyHolder = new GeneratedKeyHolder();
            jdbcTemplate.update(connection -> {
                PreparedStatement ps = connection.prepareStatement("""
                        INSERT INTO knowledge_links (
                            user_id, source_knowledge_id, target_knowledge_id,
                            relation_type, relation_note, compare_points
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, Statement.RETURN_GENERATED_KEYS);
                ps.setLong(1, userId);
                ps.setLong(2, sourceId);
                ps.setLong(3, targetId);
                ps.setString(4, relationType);
                ps.setString(5, defaultString(request.relationNote()));
                ps.setString(6, defaultString(request.comparePoints()));
                return ps;
            }, keyHolder);
            id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        } else {
            id = existing.getFirst();
            jdbcTemplate.update("""
                    UPDATE knowledge_links
                    SET relation_note = ?, compare_points = ?, created_at = datetime('now', 'localtime')
                    WHERE id = ? AND user_id = ?
                    """, defaultString(request.relationNote()), defaultString(request.comparePoints()), id, userId);
        }
        return knowledgeLinkQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Knowledge link not found."));
    }

    @Transactional
    public void delete(long id) {
        long userId = currentUserProvider.requireUserId();
        int deleted = jdbcTemplate.update("""
                DELETE FROM knowledge_links
                WHERE id = ? AND user_id = ?
                """, id, userId);
        if (deleted == 0) {
            throw new ResourceNotFoundException("Knowledge link not found.");
        }
    }

    private void ensureCardBelongsToUser(long userId, long cardId) {
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(*)
                FROM knowledge_cards
                WHERE id = ? AND user_id = ?
                """, Integer.class, cardId, userId);
        if (count == null || count == 0) {
            throw new ResourceNotFoundException("Knowledge card not found.");
        }
    }

    private String defaultRelationType(String value) {
        return value == null || value.isBlank() ? "关联" : value;
    }

    private String defaultString(String value) {
        return value == null ? "" : value.strip();
    }
}
