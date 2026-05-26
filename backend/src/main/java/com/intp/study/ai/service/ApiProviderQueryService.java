package com.intp.study.ai.service;

import com.intp.study.ai.dto.ApiProviderDto;
import com.intp.study.common.tenant.CurrentUserProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class ApiProviderQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;

    public ApiProviderQueryService(JdbcTemplate jdbcTemplate, CurrentUserProvider currentUserProvider) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
    }

    public List<ApiProviderDto> listProviders() {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT provider_key, name, provider_type, base_url, model, auth_type,
                       extra_headers_json, request_template_json, response_path,
                       balance_query_enabled, balance_query_type, balance_query_config_json,
                       enabled, sort_order, created_at, updated_at
                FROM api_providers
                WHERE user_id = ?
                ORDER BY sort_order ASC, provider_key ASC
                """, (rs, rowNum) -> new ApiProviderDto(
                rs.getString("provider_key"),
                rs.getString("name"),
                rs.getString("provider_type"),
                rs.getString("base_url"),
                rs.getString("model"),
                rs.getString("auth_type"),
                rs.getString("extra_headers_json"),
                rs.getString("request_template_json"),
                rs.getString("response_path"),
                rs.getInt("balance_query_enabled") != 0,
                rs.getString("balance_query_type"),
                rs.getString("balance_query_config_json"),
                rs.getInt("enabled") != 0,
                rs.getInt("sort_order"),
                rs.getString("created_at"),
                rs.getString("updated_at")
        ), userId);
    }

    public Optional<ApiProviderDto> findProvider(String providerKey) {
        long userId = currentUserProvider.requireUserId();
        return jdbcTemplate.query("""
                SELECT provider_key, name, provider_type, base_url, model, auth_type,
                       extra_headers_json, request_template_json, response_path,
                       balance_query_enabled, balance_query_type, balance_query_config_json,
                       enabled, sort_order, created_at, updated_at
                FROM api_providers
                WHERE user_id = ? AND provider_key = ?
                """, (rs, rowNum) -> new ApiProviderDto(
                rs.getString("provider_key"),
                rs.getString("name"),
                rs.getString("provider_type"),
                rs.getString("base_url"),
                rs.getString("model"),
                rs.getString("auth_type"),
                rs.getString("extra_headers_json"),
                rs.getString("request_template_json"),
                rs.getString("response_path"),
                rs.getInt("balance_query_enabled") != 0,
                rs.getString("balance_query_type"),
                rs.getString("balance_query_config_json"),
                rs.getInt("enabled") != 0,
                rs.getInt("sort_order"),
                rs.getString("created_at"),
                rs.getString("updated_at")
        ), userId, providerKey).stream().findFirst();
    }
}
