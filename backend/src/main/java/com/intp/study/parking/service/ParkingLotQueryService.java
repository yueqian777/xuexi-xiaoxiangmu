package com.intp.study.parking.service;

import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.parking.dto.ParkingLotItemDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class ParkingLotQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public ParkingLotQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<ParkingLotItemDto> listForCurrentUser() {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT id, subject, question, source, status, created_at
                FROM parking_lot
                WHERE user_id = ?
                ORDER BY status ASC, created_at DESC, id DESC
                """, (rs, rowNum) -> new ParkingLotItemDto(
                rs.getLong("id"),
                rs.getString("subject"),
                rs.getString("question"),
                rs.getString("source"),
                rs.getString("status"),
                rs.getString("created_at")
        ), userId);
    }

    public Optional<ParkingLotItemDto> findForCurrentUser(long id) {
        long userId = currentUserProvider.requireUserId();
        List<ParkingLotItemDto> items = jdbcTemplate.query("""
                SELECT id, subject, question, source, status, created_at
                FROM parking_lot
                WHERE user_id = ? AND id = ?
                """, (rs, rowNum) -> new ParkingLotItemDto(
                rs.getLong("id"),
                rs.getString("subject"),
                rs.getString("question"),
                rs.getString("source"),
                rs.getString("status"),
                rs.getString("created_at")
        ), userId, id);
        return items.stream().findFirst();
    }
}
