package com.intp.study.ai.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.intp.study.ai.model.AiGenerateCommand;
import com.intp.study.ai.model.AiGenerateResult;
import com.intp.study.ai.model.ApiProviderConfig;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

@Component
public class OpenAiChatProviderClient implements AiProviderClient {
    private static final String DEFAULT_MODEL = "gpt-5.5";

    private final ObjectMapper objectMapper;
    private final ProviderUrlGuard providerUrlGuard;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(30))
            .build();

    public OpenAiChatProviderClient(ObjectMapper objectMapper, ProviderUrlGuard providerUrlGuard) {
        this.objectMapper = objectMapper;
        this.providerUrlGuard = providerUrlGuard;
    }

    @Override
    public boolean supports(String providerType) {
        return "openai_chat".equals(providerType) || "minimax_chat".equals(providerType);
    }

    @Override
    public AiGenerateResult generate(ApiProviderConfig provider, AiGenerateCommand command) {
        String model = firstNonBlank(command.model(), provider.model(), DEFAULT_MODEL);
        String apiKey = resolveApiKey(provider, command.apiKey());
        Map<String, Object> body = new HashMap<>();
        body.put("model", model);
        body.put("messages", java.util.List.of(Map.of("role", "user", "content", command.prompt())));
        body.put("temperature", "minimax_chat".equals(provider.providerType()) ? 0.7 : 0.2);
        body.put("max_tokens", command.maxOutputTokens() > 0 ? command.maxOutputTokens() : 1600);
        if (command.reasoningDepth() != null && !command.reasoningDepth().isBlank() && !"关闭".equals(command.reasoningDepth())) {
            body.put("reasoning_effort", reasoningEffort(command.reasoningDepth()));
        }

        try {
            HttpRequest request = buildRequest(provider, apiKey, body);
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 400) {
                throw new IllegalArgumentException("AI provider returned HTTP " + response.statusCode() + ": " + compact(redact(response.body())));
            }
            JsonNode payload = objectMapper.readTree(response.body());
            String responsePath = firstNonBlank(provider.responsePath(), "choices.0.message.content");
            String text = extractPath(payload, responsePath);
            if (text == null || text.isBlank()) {
                throw new IllegalArgumentException("AI provider response did not contain text at path: " + responsePath);
            }
            return new AiGenerateResult(text.strip(), provider.providerKey(), model);
        } catch (IOException ex) {
            throw new IllegalArgumentException("AI provider request failed: " + ex.getMessage(), ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalArgumentException("AI provider request was interrupted.", ex);
        }
    }

    private HttpRequest buildRequest(ApiProviderConfig provider, String apiKey, Map<String, Object> body) throws IOException {
        String url = joinUrl(firstNonBlank(provider.baseUrl(), "https://api.openai.com/v1"), "chat/completions");
        Map<String, String> headers = new HashMap<>();
        headers.put("Content-Type", "application/json");
        headers.putAll(parseHeaders(provider.extraHeadersJson()));
        url = applyAuth(url, headers, provider.authType(), apiKey);
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(providerUrlGuard.requireSafeProviderUri(url))
                .timeout(Duration.ofSeconds(120))
                .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body), StandardCharsets.UTF_8));
        headers.forEach(builder::header);
        return builder.build();
    }

    private String resolveApiKey(ApiProviderConfig provider, String requestApiKey) {
        String key = firstNonBlank(requestApiKey, provider.apiKeyEnv() == null ? "" : System.getenv(provider.apiKeyEnv()));
        if ((key == null || key.isBlank()) && "本地 CLIProxyAPI".equals(provider.name())) {
            key = "local-client-key";
        }
        if ((key == null || key.isBlank()) && !"none".equals(firstNonBlank(provider.authType(), "bearer"))) {
            throw new IllegalArgumentException("Missing API key. Provide apiKey or set environment variable " + provider.apiKeyEnv() + ".");
        }
        return key == null ? "" : key;
    }

    private String applyAuth(String url, Map<String, String> headers, String authType, String apiKey) {
        String type = firstNonBlank(authType, "bearer");
        if ("none".equals(type) || apiKey == null || apiKey.isBlank()) {
            return url;
        }
        return switch (type) {
            case "x-api-key" -> {
                headers.put("x-api-key", apiKey);
                yield url;
            }
            case "api-key" -> {
                headers.put("api-key", apiKey);
                yield url;
            }
            case "x-goog-api-key" -> {
                headers.put("x-goog-api-key", apiKey);
                yield url;
            }
            case "query_key" -> url + (url.contains("?") ? "&" : "?") + "key=" + URLEncoder.encode(apiKey, StandardCharsets.UTF_8);
            default -> {
                headers.put("Authorization", "Bearer " + apiKey);
                yield url;
            }
        };
    }

    private Map<String, String> parseHeaders(String rawJson) throws IOException {
        if (rawJson == null || rawJson.isBlank()) {
            return Map.of();
        }
        JsonNode root = objectMapper.readTree(rawJson);
        if (!root.isObject()) {
            return Map.of();
        }
        Map<String, String> headers = new HashMap<>();
        Iterator<Map.Entry<String, JsonNode>> fields = root.fields();
        while (fields.hasNext()) {
            Map.Entry<String, JsonNode> entry = fields.next();
            headers.put(entry.getKey(), entry.getValue().asText());
        }
        return headers;
    }

    private String extractPath(JsonNode root, String path) {
        JsonNode current = root;
        for (String segment : path.split("\\.")) {
            if (current == null || current.isMissingNode() || current.isNull()) {
                return null;
            }
            if (segment.matches("\\d+")) {
                current = current.path(Integer.parseInt(segment));
            } else {
                current = current.path(segment);
            }
        }
        return current == null || current.isMissingNode() || current.isNull() ? null : current.asText();
    }

    private String joinUrl(String baseUrl, String suffix) {
        return baseUrl.replaceAll("/+$", "") + "/" + suffix;
    }

    private String reasoningEffort(String value) {
        return switch (value) {
            case "低" -> "low";
            case "高" -> "high";
            case "超高" -> "xhigh";
            default -> "medium";
        };
    }

    private String compact(String text) {
        if (text == null) {
            return "";
        }
        String normalized = String.join(" ", text.split("\\s+"));
        return normalized.length() <= 600 ? normalized : normalized.substring(0, 600) + "...";
    }

    private String redact(String text) {
        if (text == null) {
            return "";
        }
        return text.replaceAll("(?i)(api[_-]?key|authorization|access[_-]?token|token)\"?\\s*[:=]\\s*\"?[A-Za-z0-9._~+/=-]+", "$1=***");
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }
}
