package com.intp.study.parking.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.knowledge.dto.KnowledgeCardDto;
import com.intp.study.parking.dto.ParkingLotItemDto;
import com.intp.study.parking.dto.ConvertParkingLotToBranchQuestionRequest;
import com.intp.study.parking.dto.ConvertParkingLotToKnowledgeRequest;
import com.intp.study.parking.dto.SaveParkingLotItemRequest;
import com.intp.study.review.service.ReviewScheduleService;
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
public class ParkingLotCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final ParkingLotQueryService parkingLotQueryService;
    private final ReviewScheduleService reviewScheduleService;

    public ParkingLotCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            ParkingLotQueryService parkingLotQueryService,
            ReviewScheduleService reviewScheduleService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.parkingLotQueryService = parkingLotQueryService;
        this.reviewScheduleService = reviewScheduleService;
    }

    @Transactional
    public ParkingLotItemDto create(SaveParkingLotItemRequest request) {
        long userId = currentUserProvider.requireUserId();
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO parking_lot (user_id, subject, question, source, status)
                    VALUES (?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            ps.setLong(1, userId);
            ps.setString(2, defaultString(request.subject()));
            ps.setString(3, request.question());
            ps.setString(4, defaultString(request.source()));
            ps.setString(5, defaultStatus(request.status()));
            return ps;
        }, keyHolder);
        long id = Objects.requireNonNull(keyHolder.getKey()).longValue();
        return parkingLotQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Parking-lot item not found."));
    }

    @Transactional
    public ParkingLotItemDto update(long id, SaveParkingLotItemRequest request) {
        long userId = currentUserProvider.requireUserId();
        int updated = jdbcTemplate.update("""
                UPDATE parking_lot
                SET subject = ?, question = ?, source = ?, status = ?
                WHERE id = ? AND user_id = ?
                """,
                defaultString(request.subject()),
                request.question(),
                defaultString(request.source()),
                defaultStatus(request.status()),
                id,
                userId
        );
        if (updated == 0) {
            throw new ResourceNotFoundException("Parking-lot item not found.");
        }
        return parkingLotQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Parking-lot item not found."));
    }

    @Transactional
    public void delete(long id) {
        long userId = currentUserProvider.requireUserId();
        int deleted = jdbcTemplate.update("""
                DELETE FROM parking_lot
                WHERE id = ? AND user_id = ?
                """, id, userId);
        if (deleted == 0) {
            throw new ResourceNotFoundException("Parking-lot item not found.");
        }
    }

    @Transactional
    public ParkingLotItemDto resolve(long id) {
        long userId = currentUserProvider.requireUserId();
        updateStatus(userId, id, "已解决");
        return parkingLotQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Parking-lot item not found."));
    }

    @Transactional
    public KnowledgeCardDto convertToKnowledgeCard(long id, ConvertParkingLotToKnowledgeRequest request) {
        long userId = currentUserProvider.requireUserId();
        ParkingLotItemDto item = parkingLotQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Parking-lot item not found."));
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement("""
                    INSERT INTO knowledge_cards (
                        user_id, subject, topic, core_question, one_sentence,
                        logic_or_formula, application, mastery, need_review
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            ps.setLong(1, userId);
            ps.setString(2, item.subject().isBlank() ? "未分类" : item.subject());
            ps.setString(3, request.topic());
            ps.setString(4, item.question());
            ps.setString(5, request.oneSentence());
            ps.setString(6, defaultString(request.logicOrFormula()));
            ps.setString(7, defaultString(request.application()));
            ps.setInt(8, request.mastery());
            ps.setInt(9, request.needReview() ? 1 : 0);
            return ps;
        }, keyHolder);
        long knowledgeId = Objects.requireNonNull(keyHolder.getKey()).longValue();
        if (request.needReview()) {
            reviewScheduleService.ensureInitialReviewTasks(userId, knowledgeId, null);
        }
        updateStatus(userId, id, "已转知识点");
        return findKnowledgeCard(userId, knowledgeId);
    }

    @Transactional
    public ParkingLotItemDto convertToBranchQuestion(long id, ConvertParkingLotToBranchQuestionRequest request) {
        long userId = currentUserProvider.requireUserId();
        ParkingLotItemDto item = parkingLotQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Parking-lot item not found."));
        AnchorTarget anchor = findAnchorTarget(userId, request.anchorId());
        jdbcTemplate.update("""
                INSERT INTO branch_questions (user_id, session_id, anchor_id, question, need_review)
                VALUES (?, ?, ?, ?, 1)
                """, userId, anchor.sessionId(), request.anchorId(), item.question());
        updateStatus(userId, id, "已转插问");
        return parkingLotQueryService.findForCurrentUser(id)
                .orElseThrow(() -> new ResourceNotFoundException("Parking-lot item not found."));
    }

    private void updateStatus(long userId, long id, String status) {
        int updated = jdbcTemplate.update("""
                UPDATE parking_lot
                SET status = ?
                WHERE id = ? AND user_id = ?
                """, status, id, userId);
        if (updated == 0) {
            throw new ResourceNotFoundException("Parking-lot item not found.");
        }
    }

    private KnowledgeCardDto findKnowledgeCard(long userId, long knowledgeId) {
        List<KnowledgeCardDto> cards = jdbcTemplate.query("""
                SELECT id, subject, topic, core_question, one_sentence, logic_or_formula,
                       application, mastery, need_review, source_session_id, created_at
                FROM knowledge_cards
                WHERE id = ? AND user_id = ?
                """, (rs, rowNum) -> new KnowledgeCardDto(
                rs.getLong("id"),
                rs.getString("subject"),
                rs.getString("topic"),
                rs.getString("core_question"),
                rs.getString("one_sentence"),
                rs.getString("logic_or_formula"),
                rs.getString("application"),
                rs.getInt("mastery"),
                rs.getInt("need_review") != 0,
                rs.getObject("source_session_id", Long.class),
                rs.getString("created_at")
        ), knowledgeId, userId);
        if (cards.isEmpty()) {
            throw new ResourceNotFoundException("Knowledge card not found.");
        }
        return cards.getFirst();
    }

    private AnchorTarget findAnchorTarget(long userId, long anchorId) {
        List<AnchorTarget> anchors = jdbcTemplate.query("""
                SELECT ma.session_id
                FROM mainline_anchors ma
                JOIN study_sessions ss ON ss.id = ma.session_id AND ss.user_id = ma.user_id
                WHERE ma.id = ? AND ma.user_id = ?
                """, (rs, rowNum) -> new AnchorTarget(rs.getLong("session_id")), anchorId, userId);
        if (anchors.isEmpty()) {
            throw new ResourceNotFoundException("Mainline anchor not found.");
        }
        return anchors.getFirst();
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    private String defaultStatus(String value) {
        return value == null || value.isBlank() ? "未解决" : value;
    }

    private record AnchorTarget(long sessionId) {
    }
}
