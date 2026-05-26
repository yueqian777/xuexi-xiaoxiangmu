package com.intp.study.ai.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.intp.study.ai.model.AiGenerateCommand;
import com.intp.study.ai.model.AiGenerateResult;
import com.intp.study.ai.model.ApiProviderConfig;
import org.springframework.stereotype.Component;

import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;

@Component
public class MultiFormatProviderClient implements AiProviderClient {
    private static final Set<String> SUPPORTED = Set.of(
            "openai_responses",
            "anthropic_messages",
            "gemini_generate_content",
            "cohere_chat",
            "custom_http_json"
    );

    private final ObjectMapper objectMapper;
    private final ProviderUrlGuard providerUrlGuard;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(30))
            .build();

    public MultiFormatProviderClient(ObjectMapper objectMapper, ProviderUrlGuard providerUrlGuard) {
        this.objectMapper = objectMapper;
        this.providerUrlGuard = providerUrlGuard;
    }

    @Override
    public boolean supports(String providerType) {
        return SUPPORTED.contains(providerType);
    }

    @Override
    public AiGenerateResult generate(ApiProviderConfig provider, AiGenerateCommand command) {
        String model = firstNonBlank(command.model(), provider.model(), "gpt-5.5");
        String apiKey = resolveApiKey(provider, command.apiKey());
        try {
            RequestSpec spec = requestSpec(provider, command, model);
            Map<String, String> headers = new HashMap<>();
            headers.put("Content-Type", "application/json");
            headers.put("Accept", "application/json");
            headers.putAll(parseHeaders(provider.extraHeadersJson()));
            String url = applyAuth(spec.url(), headers, provider.authType(), apiKey);
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(providerUrlGuard.requireSafeProviderUri(url))
                    .timeout(Duration.ofSeconds(120))
                    .headers(flatten(headers))
                    .POST(HttpRequest.BodyPublishers.ofString(spec.body(), StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 400) {
                throw new IllegalArgumentException("AI provider returned HTTP " + response.statusCode() + ": " + compact(redact(response.body())));
            }
            JsonNode payload = objectMapper.readTree(response.body());
            String text = extractPath(payload, firstNonBlank(provider.responsePath(), spec.responsePath()));
            if (text == null || text.isBlank()) {
                throw new IllegalArgumentException("AI provider response did not contain text.");
            }
            return new AiGenerateResult(text.strip(), provider.providerKey(), model);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalArgumentException("AI provider request was interrupted.", ex);
        } catch (Exception ex) {
            throw new IllegalArgumentException("AI provider request failed: " + ex.getMessage(), ex);
        }
    }

    private RequestSpec requestSpec(ApiProviderConfig provider, AiGenerateCommand command, String model) throws Exception {
        return switch (provider.providerType()) {
            case "openai_responses" -> {
                ObjectNode body = objectMapper.createObjectNode();
                body.put("model", model);
                body.put("input", command.prompt());
                body.put("max_output_tokens", command.maxOutputTokens() > 0 ? command.maxOutputTokens() : 1600);
                yield new RequestSpec(join(provider.baseUrl(), "responses"), body.toString(), "output_text");
            }
            case "anthropic_messages" -> {
                ObjectNode body = objectMapper.createObjectNode();
                body.put("model", model);
                body.put("max_tokens", command.maxOutputTokens() > 0 ? command.maxOutputTokens() : 1600);
                var messages = objectMapper.createArrayNode();
                ObjectNode message = objectMapper.createObjectNode();
                message.put("role", "user");
                message.put("content", command.prompt());
                messages.add(message);
                body.set("messages", messages);
                yield new RequestSpec(join(provider.baseUrl(), "v1/messages"), body.toString(), "content.0.text");
            }
            case "gemini_generate_content" -> {
                ObjectNode body = objectMapper.createObjectNode();
                var contents = objectMapper.createArrayNode();
                ObjectNode content = objectMapper.createObjectNode();
                var parts = objectMapper.createArrayNode();
                ObjectNode part = objectMapper.createObjectNode();
                part.put("text", command.prompt());
                parts.add(part);
                content.set("parts", parts);
                contents.add(content);
                body.set("contents", contents);
                yield new RequestSpec(join(provider.baseUrl(), "v1beta/models/" + model + ":generateContent"), body.toString(), "candidates.0.content.parts.0.text");
            }
            case "cohere_chat" -> {
                ObjectNode body = objectMapper.createObjectNode();
                body.put("model", model);
                body.put("message", command.prompt());
                body.put("max_tokens", command.maxOutputTokens() > 0 ? command.maxOutputTokens() : 1600);
                yield new RequestSpec(join(provider.baseUrl(), "chat"), body.toString(), "text");
            }
            case "custom_http_json" -> customSpec(provider, command, model);
            default -> throw new IllegalArgumentException("Unsupported provider type: " + provider.providerType());
        };
    }

    private RequestSpec customSpec(ApiProviderConfig provider, AiGenerateCommand command, String model) throws Exception {
        String template = firstNonBlank(provider.requestTemplateJson(), "{\"model\":\"{{model}}\",\"prompt\":\"{{prompt}}\",\"max_tokens\":{{max_tokens}}}");
        String body = template
                .replace("{{model}}", escape(model))
                .replace("{{prompt}}", escape(command.prompt()))
                .replace("{{max_tokens}}", String.valueOf(command.maxOutputTokens() > 0 ? command.maxOutputTokens() : 1600));
        objectMapper.readTree(body);
        return new RequestSpec(provider.baseUrl(), body, firstNonBlank(provider.responsePath(), "text"));
    }

    private String resolveApiKey(ApiProviderConfig provider, String requestApiKey) {
        String key = firstNonBlank(requestApiKey, provider.apiKeyEnv() == null ? "" : System.getenv(provider.apiKeyEnv()));
        if ((key == null || key.isBlank()) && !"none".equals(firstNonBlank(provider.authType(), "bearer"))) {
            throw new IllegalArgumentException("Missing API key. Provide apiKey, unlock vault, or set environment variable " + provider.apiKeyEnv() + ".");
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
            case "query_key" -> url + (url.contains("?") ? "&" : "?") + "key=" + java.net.URLEncoder.encode(apiKey, StandardCharsets.UTF_8);
            default -> {
                headers.put("Authorization", "Bearer " + apiKey);
                yield url;
            }
        };
    }

    private Map<String, String> parseHeaders(String rawJson) throws Exception {
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

    private String[] flatten(Map<String, String> headers) {
        return headers.entrySet().stream()
                .flatMap(entry -> java.util.stream.Stream.of(entry.getKey(), entry.getValue()))
                .toArray(String[]::new);
    }

    private String extractPath(JsonNode root, String path) {
        JsonNode current = root;
        for (String segment : path.split("\\.")) {
            current = segment.matches("\\d+") ? current.path(Integer.parseInt(segment)) : current.path(segment);
        }
        return current.isMissingNode() || current.isNull() ? null : current.asText();
    }

    private String join(String baseUrl, String suffix) {
        return firstNonBlank(baseUrl, "https://api.openai.com/v1").replaceAll("/+$", "") + "/" + suffix.replaceAll("^/+", "");
    }

    private String escape(String value) {
        try {
            String json = objectMapper.writeValueAsString(value == null ? "" : value);
            return json.substring(1, json.length() - 1);
        } catch (Exception ex) {
            return "";
        }
    }

    private String compact(String text) {
        String normalized = text == null ? "" : String.join(" ", text.split("\\s+"));
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

    private record RequestSpec(String url, String body, String responsePath) {
    }
}
