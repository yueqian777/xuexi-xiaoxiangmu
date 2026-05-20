from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from db import execute, fetch_all, fetch_one, insert_and_get_id

DEFAULT_MODEL = "gpt-5.5"

PROVIDER_TYPES = {
    "openai_responses": "OpenAI Responses API",
    "openai_chat": "OpenAI 兼容 Chat Completions",
    "anthropic_messages": "Anthropic Messages API",
    "gemini_generate_content": "Google Gemini generateContent",
    "custom_http_json": "自定义 HTTP JSON",
}

DEFAULT_PROVIDERS = [
    {
        "name": "OpenAI Responses",
        "provider_type": "openai_responses",
        "base_url": "https://api.openai.com/v1",
        "model": DEFAULT_MODEL,
        "api_key_env": "OPENAI_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "output_text",
    },
    {
        "name": "OpenAI 兼容接口",
        "provider_type": "openai_chat",
        "base_url": "https://api.openai.com/v1",
        "model": DEFAULT_MODEL,
        "api_key_env": "OPENAI_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "本地 CLIProxyAPI",
        "provider_type": "openai_chat",
        "base_url": "http://localhost:8317/v1",
        "model": DEFAULT_MODEL,
        "api_key_env": "CLIPROXY_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "幻城网安 API",
        "provider_type": "openai_chat",
        "base_url": "https://api.iamhc.cn/v1",
        "model": "auto",
        "api_key_env": "IAMHC_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "Anthropic Messages",
        "provider_type": "anthropic_messages",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5",
        "api_key_env": "ANTHROPIC_API_KEY",
        "auth_type": "x-api-key",
        "extra_headers_json": '{"anthropic-version":"2023-06-01"}',
        "request_template_json": "",
        "response_path": "content.0.text",
    },
    {
        "name": "Google Gemini",
        "provider_type": "gemini_generate_content",
        "base_url": "https://generativelanguage.googleapis.com",
        "model": "gemini-2.5-pro",
        "api_key_env": "GEMINI_API_KEY",
        "auth_type": "query_key",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "candidates.0.content.parts.0.text",
    },
]


class AIServiceError(RuntimeError):
    pass


@dataclass
class AIProvider:
    id: int | None
    name: str
    provider_type: str
    base_url: str
    model: str
    api_key_env: str
    auth_type: str
    extra_headers_json: str
    request_template_json: str
    response_path: str
    enabled: bool = True


def ensure_default_api_providers() -> None:
    for provider in DEFAULT_PROVIDERS:
        existing = fetch_one("SELECT id FROM api_providers WHERE name = ?", (provider["name"],))
        if existing:
            continue
        insert_and_get_id(
            """
            INSERT INTO api_providers (
                name, provider_type, base_url, model, api_key_env, auth_type,
                extra_headers_json, request_template_json, response_path, enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                provider["name"],
                provider["provider_type"],
                provider["base_url"],
                provider["model"],
                provider["api_key_env"],
                provider["auth_type"],
                provider["extra_headers_json"],
                provider["request_template_json"],
                provider["response_path"],
            ),
        )


def list_api_providers(enabled_only: bool = False) -> list[dict[str, Any]]:
    where = "WHERE enabled = 1" if enabled_only else ""
    return fetch_all(
        f"""
        SELECT *
        FROM api_providers
        {where}
        ORDER BY id ASC
        """
    )


def get_api_provider(provider_id: int | None) -> AIProvider:
    row = None
    if provider_id:
        row = fetch_one("SELECT * FROM api_providers WHERE id = ?", (provider_id,))
    if row is None:
        row = fetch_one("SELECT * FROM api_providers WHERE enabled = 1 ORDER BY id ASC LIMIT 1")
    if row is None:
        raise AIServiceError("没有可用 API Provider，请先到“API 接入设置”创建。")
    return AIProvider(
        id=row["id"],
        name=row["name"],
        provider_type=row["provider_type"],
        base_url=row["base_url"] or "",
        model=row["model"] or DEFAULT_MODEL,
        api_key_env=row["api_key_env"] or "",
        auth_type=row["auth_type"] or "bearer",
        extra_headers_json=row["extra_headers_json"] or "{}",
        request_template_json=row["request_template_json"] or "",
        response_path=row["response_path"] or "",
        enabled=bool(row["enabled"]),
    )


def save_api_provider(data: dict[str, Any], provider_id: int | None = None) -> int:
    values = (
        data["name"].strip(),
        data["provider_type"],
        data.get("base_url", "").strip(),
        data.get("model", "").strip(),
        data.get("api_key_env", "").strip(),
        data.get("auth_type", "bearer"),
        _normalize_json_text(data.get("extra_headers_json", "{}"), "{}"),
        data.get("request_template_json", "").strip(),
        data.get("response_path", "").strip(),
        int(bool(data.get("enabled", True))),
    )
    if provider_id:
        execute(
            """
            UPDATE api_providers
            SET name = ?, provider_type = ?, base_url = ?, model = ?, api_key_env = ?,
                auth_type = ?, extra_headers_json = ?, request_template_json = ?,
                response_path = ?, enabled = ?, updated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            values + (provider_id,),
        )
        return provider_id
    return insert_and_get_id(
        """
        INSERT INTO api_providers (
            name, provider_type, base_url, model, api_key_env, auth_type,
            extra_headers_json, request_template_json, response_path, enabled
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )


def generate_text(
    prompt: str,
    *,
    provider_id: int | None = None,
    api_key: str | None = None,
    model_override: str | None = None,
    max_output_tokens: int = 1600,
) -> str:
    provider = get_api_provider(provider_id)
    model = (model_override or provider.model or DEFAULT_MODEL).strip()
    key = _resolve_api_key(provider, api_key)
    request = _build_request(provider, prompt, key, model, max_output_tokens)

    try:
        response = requests.request(
            method=request["method"],
            url=request["url"],
            headers=request["headers"],
            json=request["json"],
            timeout=120,
        )
    except requests.RequestException as exc:
        raise AIServiceError(f"API 请求失败：{exc}") from exc

    if response.status_code >= 400:
        raise AIServiceError(f"API 返回 HTTP {response.status_code}：{response.text[:1200]}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise AIServiceError(f"API 没有返回 JSON：{response.text[:1200]}") from exc

    output = _extract_path(payload, provider.response_path or _default_response_path(provider.provider_type))
    if isinstance(output, list):
        output = "\n".join(str(item) for item in output)
    if output is None or not str(output).strip():
        raise AIServiceError(f"没有从响应路径中提取到文本：{provider.response_path}")
    return str(output).strip()


def provider_label(provider: dict[str, Any]) -> str:
    type_label = PROVIDER_TYPES.get(provider["provider_type"], provider["provider_type"])
    model = provider.get("model") or "未设置模型"
    state = "启用" if provider.get("enabled") else "停用"
    return f"#{provider['id']} · {provider['name']} · {type_label} · {model} · {state}"


def _resolve_api_key(provider: AIProvider, api_key: str | None) -> str:
    key = (api_key or "").strip()
    if not key and provider.api_key_env:
        key = (os.getenv(provider.api_key_env) or "").strip()
    if not key and provider.name == "本地 CLIProxyAPI":
        key = "local-client-key"
    if not key and provider.auth_type != "none":
        target = provider.api_key_env or "页面临时密钥"
        raise AIServiceError(f"缺少 API Key。请在页面临时输入，或设置环境变量 {target}。")
    return key


def _build_request(
    provider: AIProvider,
    prompt: str,
    api_key: str,
    model: str,
    max_output_tokens: int,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    headers.update(_parse_json_object(provider.extra_headers_json, "额外请求头"))
    url = ""
    body: dict[str, Any] = {}

    if provider.provider_type == "openai_responses":
        url = _join_url(provider.base_url or "https://api.openai.com/v1", "responses")
        body = {"model": model, "input": prompt, "max_output_tokens": max_output_tokens}
    elif provider.provider_type == "openai_chat":
        url = _join_url(provider.base_url or "https://api.openai.com/v1", "chat/completions")
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": max_output_tokens,
        }
    elif provider.provider_type == "anthropic_messages":
        base = (provider.base_url or "https://api.anthropic.com").rstrip("/")
        if base.endswith("/v1/messages"):
            url = base
        elif base.endswith("/v1"):
            url = f"{base}/messages"
        else:
            url = f"{base}/v1/messages"
        body = {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    elif provider.provider_type == "gemini_generate_content":
        base = (provider.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        url = f"{base}/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_output_tokens},
        }
    elif provider.provider_type == "custom_http_json":
        url = provider.base_url.strip()
        body = _render_custom_body(provider.request_template_json, prompt, model, max_output_tokens)
    else:
        raise AIServiceError(f"未知 Provider 类型：{provider.provider_type}")

    url, headers = _apply_auth(url, headers, provider.auth_type, api_key)
    return {"method": "POST", "url": url, "headers": headers, "json": body}


def _apply_auth(url: str, headers: dict[str, str], auth_type: str, api_key: str) -> tuple[str, dict[str, str]]:
    if auth_type == "bearer" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "x-api-key" and api_key:
        headers["x-api-key"] = api_key
    elif auth_type == "api-key" and api_key:
        headers["api-key"] = api_key
    elif auth_type == "x-goog-api-key" and api_key:
        headers["x-goog-api-key"] = api_key
    elif auth_type == "query_key" and api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={api_key}"
    elif auth_type == "none":
        pass
    else:
        raise AIServiceError(f"不支持的鉴权方式：{auth_type}")
    return url, headers


def _join_url(base_url: str, path: str) -> str:
    base = base_url.strip().rstrip("/")
    clean_path = path.strip("/")
    if base.endswith(clean_path):
        return base
    return f"{base}/{clean_path}"


def _render_custom_body(template: str, prompt: str, model: str, max_output_tokens: int) -> dict[str, Any]:
    if not template.strip():
        raise AIServiceError("自定义 HTTP JSON Provider 必须填写请求体模板。")
    rendered = (
        template.replace("{prompt}", json.dumps(prompt, ensure_ascii=False)[1:-1])
        .replace("{model}", json.dumps(model, ensure_ascii=False)[1:-1])
        .replace("{max_output_tokens}", str(max_output_tokens))
    )
    return _parse_json_object(rendered, "自定义请求体模板")


def _parse_json_object(text: str, label: str) -> dict[str, Any]:
    normalized = _normalize_json_text(text, "{}")
    try:
        value = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise AIServiceError(f"{label} 不是合法 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise AIServiceError(f"{label} 必须是 JSON 对象。")
    return value


def _normalize_json_text(text: str, default: str) -> str:
    return text.strip() if text and text.strip() else default


def _default_response_path(provider_type: str) -> str:
    return {
        "openai_responses": "output_text",
        "openai_chat": "choices.0.message.content",
        "anthropic_messages": "content.0.text",
        "gemini_generate_content": "candidates.0.content.parts.0.text",
    }.get(provider_type, "")


def _extract_path(payload: Any, path: str) -> Any:
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise AIServiceError(f"响应路径无法访问列表下标 {part}。") from exc
        elif isinstance(current, dict):
            if part not in current:
                raise AIServiceError(f"响应路径缺少字段 {part}。")
            current = current[part]
        else:
            raise AIServiceError(f"响应路径在 {part} 处无法继续访问。")
    return current
