package com.intp.study.ai.balance.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.intp.study.ai.balance.dto.BalanceQueryRequest;
import com.intp.study.ai.balance.dto.BalanceResultDto;
import com.intp.study.ai.model.ApiProviderConfig;
import com.intp.study.ai.service.ProviderUrlGuard;
import com.intp.study.common.error.ResourceNotFoundException;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.secret.service.SecretVaultService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;

@Service
public class BalanceQueryService {
    private final JdbcTemplate jdbcTemplate;
    private final CurrentUserProvider currentUserProvider;
    private final SecretVaultService secretVaultService;
    private final ObjectMapper objectMapper;
    private final ProviderUrlGuard providerUrlGuard;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(20))
            .build();

    public BalanceQueryService(
            JdbcTemplate jdbcTemplate,
            CurrentUserProvider currentUserProvider,
            SecretVaultService secretVaultService,
            ObjectMapper objectMapper,
            ProviderUrlGuard providerUrlGuard
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.currentUserProvider = currentUserProvider;
        this.secretVaultService = secretVaultService;
        this.objectMapper = objectMapper;
        this.providerUrlGuard = providerUrlGuard;
    }

    public BalanceResultDto query(String providerKey, BalanceQueryRequest request) {
        long userId = currentUserProvider.requireUserId();
        ProviderBalanceConfig provider = findProvider(userId, providerKey);
        String credential = firstNonBlank(
                request == null ? "" : request.credential(),
                secretVaultService.resolveProviderApiKey(provider.providerKey()),
                provider.apiKeyEnv().isBlank() ? "" : System.getenv(provider.apiKeyEnv())
        );
        String qtype = firstNonBlank(request == null ? "" : request.queryType(), provider.balanceQueryType(), "generic_wallet");
        JsonNode cfg = readConfig(firstNonBlank(request == null ? "" : request.configJson(), provider.balanceQueryConfigJson(), "{}"));
        return switch (qtype) {
            case "deepseek_wallet" -> queryJson("DeepSeek", "DeepSeek 钱包余额", "https://api.deepseek.com/user/balance", credential, "balance_infos.0.total_balance", "CNY");
            case "openrouter_wallet" -> queryOpenRouter(credential);
            case "generic_wallet", "auto_wallet" -> queryGeneric(provider, credential, cfg);
            case "custom_http_json" -> queryCustom(provider, credential, cfg);
            default -> throw new IllegalArgumentException("Balance query type is not implemented yet: " + qtype);
        };
    }

    private BalanceResultDto queryOpenRouter(String credential) {
        JsonNode payload = requestJson("GET", "https://openrouter.ai/api/v1/credits", credential, null);
        JsonNode data = payload.path("data").isObject() ? payload.path("data") : payload;
        Double total = number(data.path("total_credits"));
        Double used = number(data.path("total_usage"));
        Double remaining = total == null || used == null ? null : total - used;
        return result("wallet", "OpenRouter", "OpenRouter Credits", remaining, "USD", total, used, remaining == null || remaining > 0 ? "可用" : "余额不足", "远程余额接口", payload);
    }

    private BalanceResultDto queryGeneric(ProviderBalanceConfig provider, String credential, JsonNode cfg) {
        String baseUrl = firstNonBlank(cfg.path("base_url").asText(), provider.baseUrl());
        String url = baseUrl.replaceAll("/+$", "") + "/user/balance";
        return queryJson(provider.name(), "通用钱包余额", url, credential, firstNonBlank(cfg.path("remaining_path").asText(), "balance"), cfg.path("unit_value").asText(""));
    }

    private BalanceResultDto queryCustom(ProviderBalanceConfig provider, String credential, JsonNode cfg) {
        String url = firstNonBlank(cfg.path("custom_url").asText(), provider.baseUrl());
        String method = firstNonBlank(cfg.path("custom_method").asText(), "GET").toUpperCase();
        JsonNode payload = requestJson(method, url, credential, cfg.path("custom_body").asText(null));
        String amountPath = firstNonBlank(cfg.path("remaining_path").asText(), "balance");
        return result("custom", provider.name(), "自定义 HTTP JSON 余额", number(path(payload, amountPath)), cfg.path("unit_value").asText(""), number(path(payload, cfg.path("total_path").asText(""))), number(path(payload, cfg.path("used_path").asText(""))), path(payload, cfg.path("status_path").asText("")).asText(""), "自定义接口", payload);
    }

    private BalanceResultDto queryJson(String provider, String title, String url, String credential, String amountPath, String unit) {
        JsonNode payload = requestJson("GET", url, credential, null);
        return result("wallet", provider, title, number(path(payload, amountPath)), unit, null, null, "可用", "远程余额接口", payload);
    }

    private JsonNode requestJson(String method, String url, String credential, String body) {
        try {
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                    .uri(providerUrlGuard.requireSafeProviderUri(url))
                    .timeout(Duration.ofSeconds(30));
            if (credential != null && !credential.isBlank()) {
                builder.header("Authorization", "Bearer " + credential);
            }
            builder.header("Accept", "application/json");
            if ("POST".equals(method)) {
                builder.header("Content-Type", "application/json");
                builder.POST(HttpRequest.BodyPublishers.ofString(body == null ? "{}" : body, StandardCharsets.UTF_8));
            } else {
                builder.GET();
            }
            HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 400) {
                throw new IllegalArgumentException("Balance query returned HTTP " + response.statusCode());
            }
            return objectMapper.readTree(response.body());
        } catch (Exception ex) {
            throw new IllegalArgumentException("Balance query failed: " + ex.getMessage(), ex);
        }
    }

    private ProviderBalanceConfig findProvider(long userId, String providerKey) {
        return jdbcTemplate.query("""
                SELECT provider_key, name, base_url, api_key_env, balance_query_type, balance_query_config_json
                FROM api_providers
                WHERE user_id = ? AND provider_key = ?
                """, (rs, rowNum) -> new ProviderBalanceConfig(
                rs.getString("provider_key"),
                rs.getString("name"),
                rs.getString("base_url"),
                rs.getString("api_key_env"),
                rs.getString("balance_query_type"),
                rs.getString("balance_query_config_json")
        ), userId, providerKey).stream().findFirst()
                .orElseThrow(() -> new ResourceNotFoundException("API provider not found."));
    }

    private JsonNode readConfig(String json) {
        try {
            JsonNode node = objectMapper.readTree(json == null || json.isBlank() ? "{}" : json);
            return node.isObject() ? node : objectMapper.createObjectNode();
        } catch (Exception ex) {
            return objectMapper.createObjectNode();
        }
    }

    private JsonNode path(JsonNode root, String path) {
        if (path == null || path.isBlank()) {
            return objectMapper.missingNode();
        }
        JsonNode current = root;
        for (String part : path.split("\\.")) {
            current = part.matches("\\d+") ? current.path(Integer.parseInt(part)) : current.path(part);
        }
        return current;
    }

    private Double number(JsonNode node) {
        if (node == null || node.isMissingNode() || node.isNull() || node.asText().isBlank()) {
            return null;
        }
        return node.isNumber() ? node.asDouble() : Double.parseDouble(node.asText());
    }

    private BalanceResultDto result(String kind, String provider, String title, Double amount, String unit, Double total, Double used, String status, String source, JsonNode details) {
        return new BalanceResultDto(kind, provider, title, amount, unit, total, used, status, source, details.toString());
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }

    private record ProviderBalanceConfig(
            String providerKey,
            String name,
            String baseUrl,
            String apiKeyEnv,
            String balanceQueryType,
            String balanceQueryConfigJson
    ) {
    }
}
