package com.intp.study.ai.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.intp.study.ai.dto.ApiProviderDto;
import com.intp.study.ai.dto.DefaultApiConfigDto;
import com.intp.study.ai.dto.GenerateTextRequest;
import com.intp.study.ai.dto.GenerateTextResponse;
import com.intp.study.ai.dto.ProviderTestRequest;
import com.intp.study.ai.dto.ReorderApiProviderRequest;
import com.intp.study.ai.dto.SaveApiProviderRequest;
import com.intp.study.ai.model.AiGenerateCommand;
import com.intp.study.ai.model.AiGenerateResult;
import com.intp.study.ai.model.ApiProviderConfig;
import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.secret.service.SecretVaultService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.text.Normalizer;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

@Service
public class ApiProviderCommandService {
    private static final String DEFAULT_API_SETTING_KEY = "default_api_config";
    private static final String DEFAULT_MODEL = "gpt-5.5";

    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final ApiProviderQueryService apiProviderQueryService;
    private final List<AiProviderClient> providerClients;
    private final ObjectMapper objectMapper;
    private final SecretVaultService secretVaultService;

    public ApiProviderCommandService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            ApiProviderQueryService apiProviderQueryService,
            List<AiProviderClient> providerClients,
            ObjectMapper objectMapper,
            SecretVaultService secretVaultService
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.apiProviderQueryService = apiProviderQueryService;
        this.providerClients = providerClients;
        this.objectMapper = objectMapper;
        this.secretVaultService = secretVaultService;
    }

    @Transactional
    public ApiProviderDto create(SaveApiProviderRequest request) {
        long userId = currentUserProvider.requireUserId();
        String providerKey = newProviderKey(userId, request.name());
        jdbcTemplate.update("""
                INSERT INTO api_providers (
                    provider_key, user_id, name, provider_type, base_url, model, api_key_env,
                    auth_type, extra_headers_json, request_template_json, response_path,
                    balance_query_enabled, balance_query_type, balance_query_config_json,
                    enabled, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                providerKey,
                userId,
                request.name().trim(),
                request.providerType(),
                defaultString(request.baseUrl()),
                defaultString(request.model()),
                defaultString(request.apiKeyEnv()),
                defaultString(request.authType(), "bearer"),
                normalizeJsonObject(request.extraHeadersJson(), "{}"),
                defaultString(request.requestTemplateJson()),
                defaultString(request.responsePath()),
                request.balanceQueryEnabled() ? 1 : 0,
                defaultString(request.balanceQueryType(), "auto_wallet"),
                sanitizeBalanceConfig(request.balanceQueryConfigJson()),
                request.enabled() ? 1 : 0,
                Math.max(0, request.sortOrder())
        );
        normalizeSortOrders(userId);
        placeProvider(userId, providerKey, request.sortOrder());
        return apiProviderQueryService.findProvider(providerKey)
                .orElseThrow(() -> new ResourceNotFoundException("API provider not found."));
    }

    @Transactional
    public ApiProviderDto update(String providerKey, SaveApiProviderRequest request) {
        long userId = currentUserProvider.requireUserId();
        int updated = jdbcTemplate.update("""
                UPDATE api_providers
                SET name = ?, provider_type = ?, base_url = ?, model = ?, api_key_env = ?,
                    auth_type = ?, extra_headers_json = ?, request_template_json = ?,
                    response_path = ?, balance_query_enabled = ?, balance_query_type = ?,
                    balance_query_config_json = ?, enabled = ?, updated_at = datetime('now', 'localtime')
                WHERE user_id = ? AND provider_key = ?
                """,
                request.name().trim(),
                request.providerType(),
                defaultString(request.baseUrl()),
                defaultString(request.model()),
                defaultString(request.apiKeyEnv()),
                defaultString(request.authType(), "bearer"),
                normalizeJsonObject(request.extraHeadersJson(), "{}"),
                defaultString(request.requestTemplateJson()),
                defaultString(request.responsePath()),
                request.balanceQueryEnabled() ? 1 : 0,
                defaultString(request.balanceQueryType(), "auto_wallet"),
                sanitizeBalanceConfig(request.balanceQueryConfigJson()),
                request.enabled() ? 1 : 0,
                userId,
                providerKey
        );
        if (updated == 0) {
            throw new ResourceNotFoundException("API provider not found.");
        }
        placeProvider(userId, providerKey, request.sortOrder());
        return apiProviderQueryService.findProvider(providerKey)
                .orElseThrow(() -> new ResourceNotFoundException("API provider not found."));
    }

    @Transactional
    public void delete(String providerKey) {
        long userId = currentUserProvider.requireUserId();
        int deleted = jdbcTemplate.update("DELETE FROM api_providers WHERE user_id = ? AND provider_key = ?", userId, providerKey);
        if (deleted == 0) {
            throw new ResourceNotFoundException("API provider not found.");
        }
        normalizeSortOrders(userId);
    }

    @Transactional
    public List<ApiProviderDto> reorder(List<ReorderApiProviderRequest> requests) {
        long userId = currentUserProvider.requireUserId();
        for (ReorderApiProviderRequest request : requests) {
            jdbcTemplate.update("""
                    UPDATE api_providers
                    SET sort_order = ?, enabled = ?, updated_at = datetime('now', 'localtime')
                    WHERE user_id = ? AND provider_key = ?
                    """, request.sortOrder(), request.enabled() ? 1 : 0, userId, request.providerKey());
        }
        normalizeSortOrders(userId);
        return apiProviderQueryService.listProviders();
    }

    public DefaultApiConfigDto getDefaultConfig() {
        long userId = currentUserProvider.requireUserId();
        String key = userSettingKey(DEFAULT_API_SETTING_KEY, userId);
        String value = jdbcTemplate.query("SELECT value FROM app_settings WHERE key = ?", (rs, rowNum) -> rs.getString("value"), key)
                .stream()
                .findFirst()
                .orElse("{}");
        try {
            return objectMapper.readValue(value, DefaultApiConfigDto.class);
        } catch (Exception ex) {
            return new DefaultApiConfigDto(null, null);
        }
    }

    @Transactional
    public DefaultApiConfigDto saveDefaultConfig(DefaultApiConfigDto request) {
        long userId = currentUserProvider.requireUserId();
        if (request.providerKey() != null && !request.providerKey().isBlank()) {
            apiProviderQueryService.findProvider(request.providerKey())
                    .orElseThrow(() -> new ResourceNotFoundException("API provider not found."));
        }
        try {
            String value = objectMapper.writeValueAsString(request);
            jdbcTemplate.update("""
                    INSERT INTO app_settings (key, user_id, value, updated_at)
                    VALUES (?, ?, ?, datetime('now', 'localtime'))
                    ON CONFLICT(key) DO UPDATE SET
                        user_id = excluded.user_id,
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """, userSettingKey(DEFAULT_API_SETTING_KEY, userId), userId, value);
            return request;
        } catch (Exception ex) {
            throw new IllegalArgumentException("Default API config could not be saved.", ex);
        }
    }

    public GenerateTextResponse generate(GenerateTextRequest request) {
        long userId = currentUserProvider.requireUserId();
        ApiProviderConfig provider = findConfig(userId, request.providerKey());
        AiProviderClient client = providerClients.stream()
                .filter(candidate -> candidate.supports(provider.providerType()))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("Provider type is not implemented yet: " + provider.providerType()));
        String model = defaultString(request.model(), provider.model().isBlank() ? DEFAULT_MODEL : provider.model());
        AiGenerateResult result = client.generate(provider, new AiGenerateCommand(
                request.prompt(),
                model,
                request.maxOutputTokens() == null ? 1600 : request.maxOutputTokens(),
                request.reasoningDepth(),
                firstNonBlank(request.apiKey(), secretVaultService.resolveProviderApiKey(provider.providerKey()))
        ));
        return new GenerateTextResponse(result.text(), result.providerKey(), result.model());
    }

    public GenerateTextResponse testProvider(String providerKey, ProviderTestRequest request) {
        return generate(new GenerateTextRequest(
                providerKey,
                request == null ? null : request.model(),
                "请回复：OK",
                request == null || request.maxOutputTokens() == null ? 64 : request.maxOutputTokens(),
                null,
                request == null ? null : request.apiKey()
        ));
    }

    private ApiProviderConfig findConfig(long userId, String providerKey) {
        String sql;
        Object[] args;
        if (providerKey == null || providerKey.isBlank()) {
            sql = """
                    SELECT provider_key, name, provider_type, base_url, model, api_key_env,
                           auth_type, extra_headers_json, request_template_json, response_path,
                           enabled, sort_order
                    FROM api_providers
                    WHERE user_id = ? AND enabled = 1
                    ORDER BY sort_order ASC, provider_key ASC
                    LIMIT 1
                    """;
            args = new Object[]{userId};
        } else {
            sql = """
                    SELECT provider_key, name, provider_type, base_url, model, api_key_env,
                           auth_type, extra_headers_json, request_template_json, response_path,
                           enabled, sort_order
                    FROM api_providers
                    WHERE user_id = ? AND provider_key = ?
                    """;
            args = new Object[]{userId, providerKey};
        }
        List<ApiProviderConfig> configs = jdbcTemplate.query(sql, (rs, rowNum) -> new ApiProviderConfig(
                rs.getString("provider_key"),
                rs.getString("name"),
                rs.getString("provider_type"),
                rs.getString("base_url"),
                rs.getString("model"),
                rs.getString("api_key_env"),
                rs.getString("auth_type"),
                rs.getString("extra_headers_json"),
                rs.getString("request_template_json"),
                rs.getString("response_path"),
                rs.getInt("enabled") != 0,
                rs.getInt("sort_order")
        ), args);
        if (configs.isEmpty()) {
            throw new ResourceNotFoundException("API provider not found.");
        }
        return configs.getFirst();
    }

    private void normalizeSortOrders(long userId) {
        List<String> keys = jdbcTemplate.query("""
                SELECT provider_key
                FROM api_providers
                WHERE user_id = ?
                ORDER BY CASE WHEN sort_order <= 0 THEN 1 ELSE 0 END, sort_order ASC, provider_key ASC
                """, (rs, rowNum) -> rs.getString("provider_key"), userId);
        for (int i = 0; i < keys.size(); i++) {
            jdbcTemplate.update("UPDATE api_providers SET sort_order = ? WHERE user_id = ? AND provider_key = ?", i + 1, userId, keys.get(i));
        }
    }

    private void placeProvider(long userId, String providerKey, int targetOrder) {
        if (targetOrder <= 0) {
            normalizeSortOrders(userId);
            return;
        }
        List<String> keys = jdbcTemplate.query("""
                SELECT provider_key
                FROM api_providers
                WHERE user_id = ? AND provider_key <> ?
                ORDER BY sort_order ASC, provider_key ASC
                """, (rs, rowNum) -> rs.getString("provider_key"), userId, providerKey);
        int index = Math.max(0, Math.min(keys.size(), targetOrder - 1));
        keys.add(index, providerKey);
        for (int i = 0; i < keys.size(); i++) {
            jdbcTemplate.update("UPDATE api_providers SET sort_order = ? WHERE user_id = ? AND provider_key = ?", i + 1, userId, keys.get(i));
        }
    }

    private String newProviderKey(long userId, String name) {
        Set<String> existing = new HashSet<>(jdbcTemplate.query(
                "SELECT provider_key FROM api_providers WHERE user_id = ?",
                (rs, rowNum) -> rs.getString("provider_key"),
                userId
        ));
        String base = slugify(name);
        String candidate = base;
        int suffix = 2;
        while (existing.contains(candidate)) {
            candidate = base + "-" + suffix;
            suffix++;
        }
        return candidate;
    }

    private String slugify(String value) {
        String normalized = Normalizer.normalize(value == null ? "" : value, Normalizer.Form.NFKD)
                .toLowerCase(Locale.ROOT);
        String slug = normalized.replaceAll("[^\\p{Alnum}]+", "-")
                .replaceAll("^-+|-+$", "");
        return slug.isBlank() ? "provider" : slug.substring(0, Math.min(80, slug.length()));
    }

    private String normalizeJsonObject(String value, String fallback) {
        String text = defaultString(value, fallback);
        try {
            if (!objectMapper.readTree(text).isObject()) {
                throw new IllegalArgumentException("JSON value must be an object.");
            }
            return text;
        } catch (Exception ex) {
            throw new IllegalArgumentException("Invalid JSON object: " + ex.getMessage());
        }
    }

    private String sanitizeBalanceConfig(String value) {
        try {
            com.fasterxml.jackson.databind.node.ObjectNode node = (com.fasterxml.jackson.databind.node.ObjectNode) objectMapper.readTree(defaultString(value, "{}"));
            for (String key : List.of("api_key", "apiKey", "access_token", "accessToken", "authorization", "token")) {
                node.remove(key);
            }
            return node.toString();
        } catch (Exception ex) {
            throw new IllegalArgumentException("Invalid balance query JSON object: " + ex.getMessage());
        }
    }

    private String defaultString(String value) {
        return value == null ? "" : value.trim();
    }

    private String defaultString(String value, String fallback) {
        String text = defaultString(value);
        return text.isBlank() ? fallback : text;
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }

    private String userSettingKey(String key, long userId) {
        return "user:" + userId + ":" + key;
    }
}
