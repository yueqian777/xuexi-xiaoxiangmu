from __future__ import annotations

import json
import os
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from db import execute, execute_many, fetch_all, fetch_one, insert_and_get_id

DEFAULT_MODEL = "gpt-5.5"

PROVIDER_TYPES = {
    "openai_responses": "OpenAI Responses API",
    "openai_chat": "OpenAI 兼容 Chat Completions",
    "anthropic_messages": "Anthropic Messages API",
    "gemini_generate_content": "Google Gemini generateContent",
    "cohere_chat": "Cohere Chat API",
    "custom_http_json": "自定义 HTTP JSON",
    "minimax_chat": "MiniMax Chat API",
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
        "name": "DeepSeek V4 Pro",
        "provider_type": "openai_chat",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "api_key_env": "DEEPSEEK_API_KEY",
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
    {
        "name": "MiniMax",
        "provider_type": "minimax_chat",
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-M2.7",
        "api_key_env": "MINIMAX_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    # === 2026年新增主流 Provider ===
    {
        "name": "智谱 AI (GLM)",
        "provider_type": "openai_chat",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "api_key_env": "ZHIPU_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "阿里云通义千问 (Qwen)",
        "provider_type": "openai_chat",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "api_key_env": "DASHSCOPE_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "腾讯混元 (Hunyuan)",
        "provider_type": "openai_chat",
        "base_url": "https://hunyuan.cloud.tencent.com/v1",
        "model": "hunyuan-pro",
        "api_key_env": "HUNYUAN_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "Cohere",
        "provider_type": "cohere_chat",
        "base_url": "https://api.cohere.ai/v2",
        "model": "command-r-plus",
        "api_key_env": "COHERE_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "generations.0.text",
    },
    {
        "name": "Mistral AI",
        "provider_type": "openai_chat",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-large",
        "api_key_env": "MISTRAL_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "Grok (xAI)",
        "provider_type": "openai_chat",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-3",
        "api_key_env": "XAI_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "硅基流动 (SiliconFlow)",
        "provider_type": "openai_chat",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-72B-Instruct",
        "api_key_env": "SILICONFLOW_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "字节豆包 (Doubao)",
        "provider_type": "openai_chat",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",
        "api_key_env": "DOUBAO_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "Kimi (Moonshot)",
        "provider_type": "openai_chat",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-128k",
        "api_key_env": "MOONSHOT_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "Groq",
        "provider_type": "openai_chat",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-4-scout",
        "api_key_env": "GROQ_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
    {
        "name": "Perplexity",
        "provider_type": "openai_chat",
        "base_url": "https://api.perplexity.ai",
        "model": "sonar-pro",
        "api_key_env": "PERPLEXITY_API_KEY",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": "",
        "response_path": "choices.0.message.content",
    },
]


class AIServiceError(RuntimeError):
    def __init__(self, message: str, *, category: str = "unknown", status_code: int | None = None):
        super().__init__(message)
        self.category = category
        self.status_code = status_code


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
    execute_many(
        """
        INSERT OR IGNORE INTO api_providers (
            name, provider_type, base_url, model, api_key_env, auth_type,
            extra_headers_json, request_template_json, response_path, enabled
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
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
            )
            for provider in DEFAULT_PROVIDERS
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
        raise AIServiceError("没有可用 API Provider，请先到\"API 接入设置\"创建。")
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
    image_paths: list[str] | None = None,
    reasoning_depth: str | None = None,
) -> str:
    provider = get_api_provider(provider_id)
    model = (model_override or provider.model or DEFAULT_MODEL).strip()
    key = _resolve_api_key(provider, api_key)
    request = _build_request(provider, prompt, key, model, max_output_tokens, image_paths or [], reasoning_depth)

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
        raise _build_http_error(response)

    try:
        payload = response.json()
    except ValueError as exc:
        raise AIServiceError(f"API 没有返回 JSON：{response.text[:1200]}") from exc

    output = _extract_path(payload, provider.response_path or _default_response_path(provider.provider_type))
    if isinstance(output, list):
        output = "\n".join(str(item) for item in output)
    if output is None or not str(output).strip():
        reasoning = _safe_extract_path(payload, "choices.0.message.reasoning_content")
        finish_reason = _safe_extract_path(payload, "choices.0.finish_reason")
        if reasoning and finish_reason == "length":
            raise AIServiceError("模型只返回了 reasoning，最终回答为空。请把\"最大输出 token\"调高后重试。")
        raise AIServiceError(f"没有从响应路径中提取到文本：{provider.response_path}")
    output_str = str(output).strip()
    # 对 MiniMax 始终执行思考内容移除（MiniMax 的思考内容无论是否开启推理都会出现）
    # 其他模型仅在推理深度非"关闭"时移除
    if provider.provider_type == "minimax_chat":
        output_str = _strip_thinking_content(output_str, provider.provider_type)
    elif reasoning_depth and reasoning_depth != "关闭":
        output_str = _strip_thinking_content(output_str, provider.provider_type)
    return output_str


def provider_label(provider: dict[str, Any]) -> str:
    type_label = PROVIDER_TYPES.get(provider["provider_type"], provider["provider_type"])
    model = provider.get("model") or "未设置模型"
    state = "启用" if provider.get("enabled") else "停用"
    return f"#{provider['id']} · {provider['name']} · {type_label} · {model} · {state}"


def is_quota_error(exc: Exception) -> bool:
    if isinstance(exc, AIServiceError) and exc.category == "quota":
        return True
    return _classify_api_error_text(str(exc), None) == "quota"


def _build_http_error(response: requests.Response) -> AIServiceError:
    raw_text = response.text or ""
    error_message = raw_text.strip()
    error_type = ""
    error_code = ""

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error", payload)
        if isinstance(error, dict):
            error_message = str(error.get("message") or raw_text).strip()
            error_type = str(error.get("type") or "").strip()
            error_code = str(error.get("code") or "").strip()

    category = _classify_api_error_text(
        " ".join([error_message, error_type, error_code, raw_text]),
        response.status_code,
    )
    concise = _compact_api_error_message(error_message)
    suffix_parts = []
    if error_type:
        suffix_parts.append(f"type={error_type}")
    if error_code:
        suffix_parts.append(f"code={error_code}")
    suffix = f"（{', '.join(suffix_parts)}）" if suffix_parts else ""

    if category == "quota":
        return AIServiceError(
            (
                f"API 额度或上游余额不足（HTTP {response.status_code}）{suffix}。\n"
                f"上游返回：{concise}\n"
                "处理方式：切换到仍有额度的 Provider，或到该上游控制台充值 / 更换模型后再重试。"
            ),
            category=category,
            status_code=response.status_code,
        )
    if category == "rate_limit":
        return AIServiceError(
            (
                f"API 触发频率限制（HTTP {response.status_code}）{suffix}。\n"
                f"上游返回：{concise}\n"
                "处理方式：稍后重试，或把 PPT 逐页生成范围改成 10 页 / 20 页一组。"
            ),
            category=category,
            status_code=response.status_code,
        )
    if category == "model_not_found":
        return AIServiceError(
            (
                f"当前模型在这个 Provider 下不可用（HTTP {response.status_code}）{suffix}。\n"
                f"上游返回：{concise}\n"
                "处理方式：在首页或当前页面切换为该 Provider 实际支持的模型，或更换 Provider 后再重试。"
            ),
            category=category,
            status_code=response.status_code,
        )
    if category == "model_incompatible":
        return AIServiceError(
            (
                f"当前模型不支持本次请求形式（HTTP {response.status_code}）{suffix}。\n"
                f"上游返回：{concise}\n"
                "处理方式：如果正在发送页面图片，请切换到支持视觉输入的模型；否则更换兼容模型。"
            ),
            category=category,
            status_code=response.status_code,
        )

    return AIServiceError(
        f"API 返回 HTTP {response.status_code}{suffix}：{_compact_api_error_message(raw_text)}",
        category=category,
        status_code=response.status_code,
    )


def _classify_api_error_text(text: str, status_code: int | None) -> str:
    normalized = (text or "").lower()
    quota_markers = (
        "notenoughcverror",
        "insufficient_quota",
        "quota",
        "current quota",
        "balance",
        "prepaid",
        "余额不足",
        "额度不足",
        "资源不足",
        "11210",
    )
    if any(marker in normalized for marker in quota_markers):
        return "quota"

    rate_markers = (
        "rate_limit",
        "too many requests",
        "requests per",
        "rate limit",
        "限流",
        "请求过快",
        "频率限制",
    )
    if status_code == 429 or any(marker in normalized for marker in rate_markers):
        return "rate_limit"

    model_not_found_markers = (
        "model_not_found",
        "model not found",
        "no available channel for model",
        "no channel for model",
        "unsupported model",
        "模型不存在",
        "模型不可用",
        "没有可用渠道",
        "无可用渠道",
    )
    if any(marker in normalized for marker in model_not_found_markers):
        return "model_not_found"

    incompatible_markers = (
        "model_incompatible",
        "doesnt support image input",
        "doesn't support image input",
        "support image input",
        "unsupported image",
        "image input",
        "不支持图片",
        "不支持视觉",
    )
    if any(marker in normalized for marker in incompatible_markers):
        return "model_incompatible"

    return "unknown"


def _compact_api_error_message(message: str, limit: int = 600) -> str:
    text = " ".join(str(message or "").split())
    if len(text) <= limit:
        return text or "空响应"
    return f"{text[:limit]}..."


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
    image_paths: list[str],
    reasoning_depth: str | None = None,
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
        user_content: str | list[dict[str, Any]]
        if image_paths:
            user_content = [{"type": "text", "text": prompt}]
            for image_path in image_paths:
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_uri(Path(image_path))},
                    }
                )
        else:
            user_content = prompt
        body = {
            "model": model,
            "messages": [{"role": "user", "content": user_content}],
            "temperature": 0.2,
            "max_tokens": max_output_tokens,
        }
        if reasoning_depth and reasoning_depth != "关闭":
            effort_map = {"低": "low", "中": "medium", "高": "high"}
            body["reasoning_effort"] = effort_map.get(reasoning_depth, "medium")
    elif provider.provider_type == "anthropic_messages":
        if image_paths:
            raise AIServiceError("当前 Anthropic Provider 尚未实现图片直传，请改用 OpenAI 兼容视觉接口。")
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
        if reasoning_depth and reasoning_depth != "关闭":
            budget_map = {"低": 1024, "中": 4096, "高": 10240}
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget_map.get(reasoning_depth, 4096),
            }
    elif provider.provider_type == "gemini_generate_content":
        if image_paths:
            raise AIServiceError("当前 Gemini Provider 尚未实现图片直传，请改用 OpenAI 兼容视觉接口。")
        base = (provider.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        url = f"{base}/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_output_tokens},
        }
    elif provider.provider_type == "custom_http_json":
        if image_paths:
            raise AIServiceError("自定义 HTTP JSON Provider 尚未实现图片直传。")
        url = provider.base_url.strip()
        body = _render_custom_body(provider.request_template_json, prompt, model, max_output_tokens)
    elif provider.provider_type == "minimax_chat":
        url = _join_url(provider.base_url or "https://api.minimax.chat/v1", "chat/completions")
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": max_output_tokens,
        }
    elif provider.provider_type == "cohere_chat":
        url = _join_url(provider.base_url or "https://api.cohere.ai/v2", "chat")
        body = {
            "model": model,
            "message": prompt,
            "max_tokens": max_output_tokens,
            "temperature": 0.7,
        }
    else:
        raise AIServiceError(f"未知 Provider 类型：{provider.provider_type}")

    # DeepSeek special handling via extra_body
    if "deepseek" in (provider.name or "").lower() or "deepseek" in model.lower():
        if reasoning_depth == "关闭":
            body["extra_body"] = {"enable_thinking": False}
        elif reasoning_depth:
            body["extra_body"] = {"enable_thinking": True}

    url, headers = _apply_auth(url, headers, provider.auth_type, api_key)
    return {"method": "POST", "url": url, "headers": headers, "json": body}


def _image_data_uri(path: Path) -> str:
    if not path.exists():
        raise AIServiceError(f"页面图片不存在：{path}")
    suffix = path.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


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


def list_available_models(
    provider: dict[str, Any],
    api_key: str | None = None,
) -> list[str]:
    """获取 provider 支持的模型列表，失败时返回空列表。"""
    try:
        return _list_models_impl(provider, api_key)
    except Exception:
        return []


def _list_models_impl(provider: dict[str, Any], api_key: str | None) -> list[str]:
    """各 provider 的 list_models 实现。"""
    provider_type = provider.get("provider_type", "")
    base_url = (provider.get("base_url") or "").strip().rstrip("/")
    key = _resolve_api_key_for_list(provider, api_key)

    if provider_type in ("openai_responses", "openai_chat"):
        return _list_openai_models(base_url, key)
    if provider_type == "anthropic_messages":
        return _list_anthropic_models(base_url, key)
    if provider_type == "gemini_generate_content":
        return _list_gemini_models(provider, api_key)
    if provider_type == "minimax_chat":
        return _list_minimax_models(base_url, key)
    if provider_type == "cohere_chat":
        return _list_cohere_models(base_url, key)
    return []


def _resolve_api_key_for_list(provider: dict[str, Any], api_key: str | None) -> str:
    """从 api_key 或环境变量获取 API key。"""
    key = (api_key or "").strip()
    if not key and provider.get("api_key_env"):
        key = (os.getenv(provider["api_key_env"]) or "").strip()
    if not key and provider.get("name") == "本地 CLIProxyAPI":
        key = "local-client-key"
    return key


def _list_openai_models(base_url: str, api_key: str) -> list[str]:
    """通过 OpenAI 兼容的 /models 接口获取模型列表。"""
    if not base_url or not api_key:
        return []
    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    models: list[str] = []
    for item in data.get("data", []):
        mid = item.get("id") or item.get("id")
        if mid:
            models.append(str(mid))
    return sorted(set(models))


def _list_anthropic_models(_base_url: str, _api_key: str) -> list[str]:
    """Anthropic 不提供 list_models API，返回已知模型列表。"""
    # Anthropic 没有公开的 list_models 接口，基于已知模型返回
    known = [
        "claude-sonnet-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "claude-opus-4-7",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
        "claude-3-sonnet-latest",
        "claude-3-haiku-latest",
    ]
    return known


def _list_gemini_models(provider: dict[str, Any], api_key: str | None) -> list[str]:
    """通过 Google AI models:list API 获取模型列表。"""
    key = _resolve_api_key_for_list(provider, api_key)
    if not key:
        return []
    base = (provider.get("base_url") or "https://generativelanguage.googleapis").rstrip("/")
    url = f"{base}/v1beta/models?key={key}"
    try:
        resp = requests.get(url, timeout=30)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    models = []
    for m in data.get("models", []):
        name = m.get("name", "")
        if name:
            models.append(name.removeprefix("models/"))
    return sorted(set(models))


def _list_minimax_models(base_url: str, api_key: str) -> list[str]:
    """通过 MiniMax /v1/models 接口获取模型列表。"""
    if not base_url or not api_key:
        return []
    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    models = []
    for item in data.get("data", []):
        mid = item.get("id") or item.get("model_id") or item.get("name")
        if mid:
            models.append(str(mid))
    return sorted(set(models))


def _list_cohere_models(base_url: str, api_key: str) -> list[str]:
    """通过 Cohere /v2/models 接口获取模型列表。"""
    if not base_url or not api_key:
        return []
    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    models = []
    for m in data.get("models", []):
        mid = m.get("name") or m.get("id")
        if mid:
            models.append(str(mid))
    return sorted(set(models))


def _default_response_path(provider_type: str) -> str:
    return {
        "openai_responses": "output_text",
        "openai_chat": "choices.0.message.content",
        "anthropic_messages": "content.0.text",
        "gemini_generate_content": "candidates.0.content.parts.0.text",
        "minimax_chat": "choices.0.message.content",
        "cohere_chat": "generations.0.text",
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


def _safe_extract_path(payload: Any, path: str) -> Any:
    try:
        return _extract_path(payload, path)
    except AIServiceError:
        return None


def _strip_thinking_content(text: str, provider_type: str) -> str:
    if not text:
        return text
    if provider_type == "anthropic_messages":
        return _strip_anthropic_thinking(text)
    return _strip_generic_thinking(text)


def _strip_anthropic_thinking(text: str) -> str:
    import re
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    text = re.sub(r'\\[thinking\\].*?\\[/thinking\\]', '', text, flags=re.DOTALL)
    return text.strip()


def _strip_generic_thinking(text: str) -> str:
    import re

    # 常见思考标签（中英文）
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[think\].*?\[/think\]', '', text, flags=re.DOTALL)
    text = re.sub(r'«thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    text = re.sub(r'<思考>.*?</思考>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[思考\].*?\[/思考\]', '', text, flags=re.DOTALL)
    text = re.sub(r'\[推理\].*?\[/推理\]', '', text, flags=re.DOTALL)
    text = re.sub(r'<推理中>.*?</推理中>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[分析中\].*?\[/分析中\]', '', text, flags=re.DOTALL)
    text = re.sub(r'\[thought\].*?\[/thought\]', '', text, flags=re.DOTALL)

    # 自然语言思考过程描述
    thinking_patterns = [
        r'思考过程[：:]\s*[\s\S]*?(?=\n\n|\Z)',
        r'推理过程[：:]\s*[\s\S]*?(?=\n\n|\Z)',
        r'分析过程[：:]\s*[\s\S]*?(?=\n\n|\Z)',
        r'让我仔细想一想[：:]*[\s\S]*?(?=\n\n|\Z)',
        r'让我思考一下[：:]*[\s\S]*?(?=\n\n|\Z)',
        r'我来分析一下[：:]*[\s\S]*?(?=\n\n|\Z)',
        r'首先[，,]?我需要[^\n]*[。\n]',
        r'第一步[，,]?[^\n]*[。\n]',
        r'Thinking process[,:]*[\s\S]*?(?=\n\n|\Z)',
        r'Let me think[,:]*[\s\S]*?(?=\n\n|\Z)',
        r"Let me analyze[,:]*[\s\S]*?(?=\n\n|\Z)",
        r'First[,. ]?I need to[^\n]*[.\n]',
        r"I'll think step by step[^\n]*[.\n]",
    ]
    for pattern in thinking_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # 移除独立成行的思考过程段落（常见于推理模型）
    lines = text.split('\n')
    filtered_lines = []
    skip_until_blank = False
    for line in lines:
        stripped = line.strip()
        if re.match(r'^(思考中|推理中|分析中|正在分析|正在推理|thinking|analyzing)', stripped, re.IGNORECASE):
            skip_until_blank = True
            continue
        if skip_until_blank:
            if not stripped:
                skip_until_blank = False
            continue
        filtered_lines.append(line)
    text = '\n'.join(filtered_lines)

    return text.strip()
