package com.intp.study.parking.service;

import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.parking.dto.ParkingLotItemDto;
import com.intp.study.parking.dto.SaveParkingLotItemRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.Objects;

@Service
public class ParkingLotCommandService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final ParkingLotQueryService parkingLotQueryService;

    public ParkingLotCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            ParkingLotQueryService parkingLotQueryService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.parkingLotQueryService = parkingLotQueryService;
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

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    private String defaultStatus(String value) {
        return value == null || value.isBlank() ? "未解决" : value;
    }
}
