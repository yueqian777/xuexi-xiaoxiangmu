package com.intp.study.secret.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.intp.study.common.tenant.CurrentUserProvider;
import com.intp.study.secret.dto.ProviderSecretPublicDto;
import com.intp.study.secret.dto.UnlockVaultRequest;
import com.intp.study.secret.dto.UpsertProviderSecretRequest;
import com.intp.study.secret.dto.VaultStatusDto;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.AEADBadTagException;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class SecretVaultService {
    private static final int KDF_ITERATIONS = 390_000;
    private static final int GCM_TAG_BITS = 128;

    private final CurrentUserProvider currentUserProvider;
    private final ObjectMapper objectMapper;
    private final Path storageRoot;
    private final SecureRandom secureRandom = new SecureRandom();
    private final Map<Long, String> unlockedPasswords = new ConcurrentHashMap<>();

    public SecretVaultService(
            CurrentUserProvider currentUserProvider,
            ObjectMapper objectMapper,
            @Value("${intp.storage.root:data}") String storageRoot
    ) {
        this.currentUserProvider = currentUserProvider;
        this.objectMapper = objectMapper;
        this.storageRoot = Path.of(storageRoot).toAbsolutePath().normalize();
    }

    public VaultStatusDto status() {
        long userId = currentUserProvider.requireUserId();
        return new VaultStatusDto(Files.isRegularFile(vaultPath(userId)), unlockedPasswords.containsKey(userId));
    }

    public VaultStatusDto unlock(UnlockVaultRequest request) {
        long userId = currentUserProvider.requireUserId();
        readVault(userId, request.masterPassword());
        unlockedPasswords.put(userId, request.masterPassword());
        return status();
    }

    public VaultStatusDto lock() {
        unlockedPasswords.remove(currentUserProvider.requireUserId());
        return status();
    }

    public List<ProviderSecretPublicDto> listPublicIndex() {
        long userId = currentUserProvider.requireUserId();
        Path path = vaultPath(userId);
        if (!Files.isRegularFile(path)) {
            return List.of();
        }
        try {
            JsonNode root = objectMapper.readTree(Files.readString(path, StandardCharsets.UTF_8));
            if (root.path("user_id").asLong(userId) != userId) {
                return List.of();
            }
            JsonNode providers = root.path("public_index").path("providers");
            if (!providers.isArray()) {
                return List.of();
            }
            java.util.ArrayList<ProviderSecretPublicDto> result = new java.util.ArrayList<>();
            for (JsonNode item : providers) {
                result.add(new ProviderSecretPublicDto(
                        item.path("provider_key").asText(""),
                        item.path("provider_name").asText(""),
                        item.path("model").asText(""),
                        item.path("provider_type").asText(""),
                        item.path("base_url").asText(""),
                        item.path("updated_at").asText("")
                ));
            }
            return result;
        } catch (Exception ex) {
            return List.of();
        }
    }

    public ProviderSecretPublicDto upsert(String providerKey, UpsertProviderSecretRequest request) {
        long userId = currentUserProvider.requireUserId();
        String password = requireUnlockedPassword(userId);
        ObjectNode data = readVault(userId, password);
        ObjectNode providers = objectObject(data, "providers");
        ObjectNode item = objectMapper.createObjectNode();
        item.put("provider_key", providerKey);
        item.put("provider_name", defaultString(request.providerName()));
        item.put("model", defaultString(request.model()));
        item.put("provider_type", defaultString(request.providerType()));
        item.put("base_url", defaultString(request.baseUrl()));
        item.put("api_key", request.apiKey().strip());
        item.put("updated_at", now());
        providers.set(providerKey, item);
        writeVault(userId, password, data);
        return new ProviderSecretPublicDto(
                providerKey,
                item.path("provider_name").asText(""),
                item.path("model").asText(""),
                item.path("provider_type").asText(""),
                item.path("base_url").asText(""),
                item.path("updated_at").asText("")
        );
    }

    public void delete(String providerKey) {
        long userId = currentUserProvider.requireUserId();
        String password = requireUnlockedPassword(userId);
        ObjectNode data = readVault(userId, password);
        objectObject(data, "providers").remove(providerKey);
        writeVault(userId, password, data);
    }

    public String resolveProviderApiKey(String providerKey) {
        long userId = currentUserProvider.requireUserId();
        String password = unlockedPasswords.get(userId);
        if (password == null) {
            return "";
        }
        ObjectNode data = readVault(userId, password);
        return data.path("providers").path(providerKey).path("api_key").asText("");
    }

    private ObjectNode readVault(long userId, String password) {
        Path path = vaultPath(userId);
        if (!Files.isRegularFile(path)) {
            ObjectNode data = objectMapper.createObjectNode();
            data.put("user_id", userId);
            data.set("providers", objectMapper.createObjectNode());
            return data;
        }
        if (password == null || password.isBlank()) {
            throw new IllegalArgumentException("请输入主密码。");
        }
        try {
            JsonNode root = objectMapper.readTree(Files.readString(path, StandardCharsets.UTF_8));
            byte[] salt = b64(root.path("salt").asText());
            byte[] nonce = b64(root.path("nonce").asText());
            byte[] ciphertext = b64(root.path("ciphertext").asText());
            SecretKey key = deriveKey(password, salt, root.path("iterations").asInt(KDF_ITERATIONS));
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(GCM_TAG_BITS, nonce));
            JsonNode data = objectMapper.readTree(cipher.doFinal(ciphertext));
            if (!data.isObject() || data.path("user_id").asLong(userId) != userId) {
                throw new IllegalArgumentException("密钥库用户不匹配。");
            }
            return (ObjectNode) data;
        } catch (AEADBadTagException ex) {
            throw new IllegalArgumentException("主密码不正确，无法解密 API Key。", ex);
        } catch (Exception ex) {
            throw new IllegalArgumentException("加密密钥库文件损坏或格式不正确。", ex);
        }
    }

    private void writeVault(long userId, String password, ObjectNode data) {
        try {
            Files.createDirectories(storageRoot);
            byte[] salt = randomBytes(16);
            byte[] nonce = randomBytes(12);
            SecretKey key = deriveKey(password, salt, KDF_ITERATIONS);
            data.put("user_id", userId);
            data.put("updated_at", now());
            byte[] plaintext = objectMapper.writeValueAsBytes(data);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(GCM_TAG_BITS, nonce));
            ObjectNode root = objectMapper.createObjectNode();
            root.put("version", 1);
            root.put("algorithm", "AES-256-GCM");
            root.put("kdf", "PBKDF2-HMAC-SHA256");
            root.put("iterations", KDF_ITERATIONS);
            root.put("user_id", userId);
            root.put("salt", b64(salt));
            root.put("nonce", b64(nonce));
            root.put("ciphertext", b64(cipher.doFinal(plaintext)));
            root.set("public_index", publicIndex(data));
            root.put("updated_at", data.path("updated_at").asText(""));
            Files.writeString(vaultPath(userId), objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(root), StandardCharsets.UTF_8);
        } catch (Exception ex) {
            throw new IllegalArgumentException("加密密钥库无法保存。", ex);
        }
    }

    private ObjectNode publicIndex(ObjectNode data) {
        ObjectNode index = objectMapper.createObjectNode();
        var providers = objectMapper.createArrayNode();
        data.path("providers").fields().forEachRemaining(entry -> {
            JsonNode item = entry.getValue();
            ObjectNode publicItem = objectMapper.createObjectNode();
            publicItem.put("provider_key", item.path("provider_key").asText(entry.getKey()));
            publicItem.put("provider_name", item.path("provider_name").asText(""));
            publicItem.put("model", item.path("model").asText(""));
            publicItem.put("provider_type", item.path("provider_type").asText(""));
            publicItem.put("base_url", item.path("base_url").asText(""));
            publicItem.put("updated_at", item.path("updated_at").asText(""));
            providers.add(publicItem);
        });
        index.set("providers", providers);
        return index;
    }

    private ObjectNode objectObject(ObjectNode parent, String field) {
        if (!parent.path(field).isObject()) {
            parent.set(field, objectMapper.createObjectNode());
        }
        return (ObjectNode) parent.path(field);
    }

    private String requireUnlockedPassword(long userId) {
        String password = unlockedPasswords.get(userId);
        if (password == null || password.isBlank()) {
            throw new IllegalArgumentException("密钥库尚未解锁。");
        }
        return password;
    }

    private Path vaultPath(long userId) {
        return storageRoot.resolve("api_keys_user_" + userId + ".enc.json").normalize();
    }

    private SecretKey deriveKey(String password, byte[] salt, int iterations) throws Exception {
        PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, iterations, 256);
        byte[] encoded = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
        return new SecretKeySpec(encoded, "AES");
    }

    private byte[] randomBytes(int size) {
        byte[] bytes = new byte[size];
        secureRandom.nextBytes(bytes);
        return bytes;
    }

    private byte[] b64(String value) {
        return Base64.getUrlDecoder().decode(value);
    }

    private String b64(byte[] value) {
        return Base64.getUrlEncoder().encodeToString(value);
    }

    private String now() {
        return LocalDateTime.now().withNano(0).toString();
    }

    private String defaultString(String value) {
        return value == null ? "" : value.strip();
    }
}
