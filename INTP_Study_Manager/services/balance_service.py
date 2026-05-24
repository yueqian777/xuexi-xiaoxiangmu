from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

from db import execute


class BalanceQueryError(RuntimeError):
    pass


BALANCE_QUERY_TYPES = {
    "auto_wallet": "自动识别（按 CC Switch 内置规则优先）",
    "kimi_token_plan": "CC Switch: Kimi For Coding Token Plan",
    "zhipu_token_plan": "CC Switch: 智谱 GLM Token Plan",
    "minimax_token_plan": "CC Switch: MiniMax Token Plan / Credits",
    "deepseek_wallet": "DeepSeek 钱包余额",
    "openrouter_wallet": "OpenRouter Credits",
    "siliconflow_wallet": "SiliconFlow 余额",
    "stepfun_wallet": "StepFun 余额",
    "novita_wallet": "Novita AI 余额",
    "newapi_user": "CC Switch: New API / One API 用户额度",
    "openai_plan": "ChatGPT / Codex 官方 Plan 配额",
    "generic_wallet": "CC Switch: 通用 /user/balance 钱包接口",
    "custom_http_json": "自定义 HTTP JSON",
}

WALLET_PROVIDER_HINTS = [
    "Kimi For Coding Token Plan",
    "智谱 GLM Token Plan",
    "MiniMax Token Plan / Credits",
    "DeepSeek",
    "OpenRouter",
    "SiliconFlow",
    "StepFun",
    "Novita AI",
    "New API / One API",
    "通用 HTTP JSON",
]

DEFAULT_BALANCE_QUERY_CONFIG: dict[str, Any] = {
    "timeout": 10,
    "base_url": "",
    "credential_env": "",
    "access_token_env": "",
    "account_id": "",
    "user_id": "",
    "group_id": "",
    "quota_unit": 500000,
    "custom_url": "",
    "custom_method": "GET",
    "custom_headers_json": "{}",
    "custom_body": "",
    "remaining_path": "",
    "total_path": "",
    "used_path": "",
    "unit_path": "",
    "unit_value": "",
    "status_path": "",
    "plan_name_path": "",
    "reset_path": "",
}


def balance_query_label(query_type: str) -> str:
    return BALANCE_QUERY_TYPES.get(query_type, query_type or "未知查询类型")


def load_balance_query_config(provider: dict[str, Any]) -> dict[str, Any]:
    raw = str(provider.get("balance_query_config_json") or "{}")
    try:
        saved = json.loads(raw)
    except json.JSONDecodeError:
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {**DEFAULT_BALANCE_QUERY_CONFIG, **saved}


def save_balance_query_config(
    provider_key: str,
    *,
    enabled: bool,
    query_type: str,
    config: dict[str, Any],
) -> None:
    safe_config = dict(config)
    # 敏感凭据只允许走会话、环境变量或加密密钥库，不写进 SQLite。
    for secret_key in ["api_key", "access_token", "authorization", "token"]:
        safe_config.pop(secret_key, None)
    execute(
        """
        UPDATE api_providers
        SET balance_query_enabled = ?,
            balance_query_type = ?,
            balance_query_config_json = ?,
            updated_at = datetime('now', 'localtime')
        WHERE provider_key = ?
        """,
        (
            int(bool(enabled)),
            query_type if query_type in BALANCE_QUERY_TYPES else "auto_wallet",
            json.dumps(safe_config, ensure_ascii=False),
            provider_key,
        ),
    )


def query_provider_balance(
    provider: dict[str, Any],
    *,
    credential: str | None = None,
    query_type: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = {**load_balance_query_config(provider), **(config or {})}
    qtype = query_type or str(provider.get("balance_query_type") or "auto_wallet")
    qtype = qtype if qtype in BALANCE_QUERY_TYPES else "auto_wallet"
    timeout = _timeout(cfg)

    if qtype == "auto_wallet":
        qtype = _detect_wallet_query_type(_base_url(provider, cfg))
        if not qtype:
            return _query_auto_wallet(provider, credential, cfg, timeout)

    if qtype == "kimi_token_plan":
        return _query_kimi_token_plan(_resolve_credential(provider, credential, cfg), timeout)
    if qtype == "zhipu_token_plan":
        return _query_zhipu_token_plan(_resolve_credential(provider, credential, cfg), timeout)
    if qtype == "minimax_token_plan":
        return _query_minimax_token_plan(_resolve_credential(provider, credential, cfg), cfg, timeout)
    if qtype == "deepseek_wallet":
        return _query_deepseek(_resolve_credential(provider, credential, cfg), timeout)
    if qtype == "openrouter_wallet":
        return _query_openrouter(_resolve_credential(provider, credential, cfg), timeout)
    if qtype == "siliconflow_wallet":
        return _query_siliconflow(_base_url(provider, cfg), _resolve_credential(provider, credential, cfg), timeout)
    if qtype == "stepfun_wallet":
        return _query_stepfun(_resolve_credential(provider, credential, cfg), timeout)
    if qtype == "novita_wallet":
        return _query_novita(_resolve_credential(provider, credential, cfg), timeout)
    if qtype == "newapi_user":
        return _query_newapi_user(_base_url(provider, cfg), _resolve_access_token(provider, credential, cfg), cfg, timeout)
    if qtype == "openai_plan":
        return _query_openai_plan(_resolve_access_token(provider, credential, cfg), cfg, timeout)
    if qtype == "generic_wallet":
        return _query_generic_wallet(_base_url(provider, cfg), _resolve_credential(provider, credential, cfg), cfg, timeout)
    if qtype == "custom_http_json":
        return _query_custom_http(provider, credential or "", cfg, timeout)

    raise BalanceQueryError(f"暂不支持的查询类型：{qtype}")


def _query_deepseek(api_key: str, timeout: int) -> dict[str, Any]:
    payload = _request_json(
        "GET",
        "https://api.deepseek.com/user/balance",
        headers=_bearer_headers(api_key),
        timeout=timeout,
        label="DeepSeek 余额",
    )
    rows = []
    total = 0.0
    has_total = False
    for item in payload.get("balance_infos") or []:
        amount = _to_float(item.get("total_balance"))
        if amount is not None:
            total += amount
            has_total = True
        rows.append(
            {
                "币种": item.get("currency") or "",
                "总余额": item.get("total_balance") or "",
                "赠送余额": item.get("granted_balance") or "",
                "充值余额": item.get("topped_up_balance") or "",
            }
        )
    return _result(
        kind="wallet",
        provider="DeepSeek",
        title="DeepSeek 钱包余额",
        amount=total if has_total else None,
        unit="CNY",
        status="可用" if payload.get("is_available", True) else "不可用",
        source="远程余额接口",
        details={"is_available": payload.get("is_available")},
        rows=rows,
    )


def _query_openrouter(api_key: str, timeout: int) -> dict[str, Any]:
    payload = _request_json(
        "GET",
        "https://openrouter.ai/api/v1/credits",
        headers=_bearer_headers(api_key),
        timeout=timeout,
        label="OpenRouter Credits",
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    total = _to_float(data.get("total_credits"))
    used = _to_float(data.get("total_usage"))
    remaining = total - used if total is not None and used is not None else None
    return _result(
        kind="wallet",
        provider="OpenRouter",
        title="OpenRouter Credits",
        amount=remaining,
        unit="USD",
        total=total,
        used=used,
        status="可用" if remaining is None or remaining > 0 else "余额不足",
        source="远程余额接口",
        details={"total_credits": total, "total_usage": used},
    )


def _query_siliconflow(base_url: str, api_key: str, timeout: int) -> dict[str, Any]:
    origin = _origin(base_url)
    payload = _request_json(
        "GET",
        f"{origin}/v1/user/info",
        headers=_bearer_headers(api_key),
        timeout=timeout,
        label="SiliconFlow 余额",
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    amount = _first_number(data, ["totalBalance", "balance", "total_balance", "available_balance", "chargeBalance"])
    unit = "CNY" if ".cn" in origin else "USD"
    return _result(
        kind="wallet",
        provider="SiliconFlow",
        title="SiliconFlow 账户余额",
        amount=amount,
        unit=unit,
        status=str(data.get("status") or "可用"),
        source="远程余额接口",
        details={key: data.get(key) for key in ["totalBalance", "balance", "chargeBalance", "status"] if key in data},
    )


def _query_stepfun(api_key: str, timeout: int) -> dict[str, Any]:
    payload = _request_json(
        "GET",
        "https://api.stepfun.com/v1/accounts",
        headers=_bearer_headers(api_key),
        timeout=timeout,
        label="StepFun 余额",
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    amount = _first_number(data, ["balance", "total_cash_balance", "total_voucher_balance", "total_balance"])
    return _result(
        kind="wallet",
        provider="StepFun",
        title="StepFun 账户余额",
        amount=amount,
        unit="CNY",
        source="远程余额接口",
        details=data,
    )


def _query_novita(api_key: str, timeout: int) -> dict[str, Any]:
    payload = _request_json(
        "GET",
        "https://api.novita.ai/v3/user/balance",
        headers=_bearer_headers(api_key),
        timeout=timeout,
        label="Novita AI 余额",
    )
    amount = _first_number(payload, ["availableBalanceUSD", "available_balance_usd", "balance"])
    if amount is None:
        raw_available = _to_float(payload.get("availableBalance"))
        amount = raw_available / 10000 if raw_available is not None else None
    return _result(
        kind="wallet",
        provider="Novita AI",
        title="Novita AI 账户余额",
        amount=amount,
        unit="USD",
        status="可用" if amount is None or amount > 0 else "余额不足",
        source="远程余额接口",
        details=payload,
    )


def _query_kimi_token_plan(api_key: str, timeout: int) -> dict[str, Any]:
    payload = _request_json(
        "GET",
        "https://api.kimi.com/coding/v1/usages",
        headers=_bearer_headers(api_key),
        timeout=timeout,
        label="Kimi For Coding Token Plan",
    )
    rows: list[dict[str, str]] = []
    primary_remaining = None
    primary_total = None
    primary_used = None

    limits = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    for index, item in enumerate(limits, start=1):
        if not isinstance(item, dict):
            continue
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else item
        total = _to_float(detail.get("limit"))
        remaining = _to_float(detail.get("remaining"))
        used = max(0.0, total - remaining) if total is not None and remaining is not None else None
        if primary_remaining is None and remaining is not None:
            primary_remaining = remaining
            primary_total = total
            primary_used = used
        rows.append(
            {
                "项目": str(item.get("name") or item.get("type") or f"滚动窗口 {index}"),
                "已用": _number_text(used),
                "总额度": _number_text(total),
                "剩余": _number_text(remaining),
                "重置时间": _format_reset_time(detail.get("resetTime")),
            }
        )

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    if usage:
        total = _to_float(usage.get("limit"))
        remaining = _to_float(usage.get("remaining"))
        used = max(0.0, total - remaining) if total is not None and remaining is not None else None
        if primary_remaining is None and remaining is not None:
            primary_remaining = remaining
            primary_total = total
            primary_used = used
        rows.append(
            {
                "项目": "总体 / 周额度",
                "已用": _number_text(used),
                "总额度": _number_text(total),
                "剩余": _number_text(remaining),
                "重置时间": _format_reset_time(usage.get("resetTime")),
            }
        )

    return _result(
        kind="plan",
        provider="Kimi For Coding",
        title="Kimi For Coding Token Plan 额度",
        amount=primary_remaining,
        unit="tokens",
        total=primary_total,
        used=primary_used,
        status="可用" if primary_remaining is None or primary_remaining > 0 else "额度已用完",
        source="Kimi 官方 Token Plan 接口",
        details=payload,
        rows=rows,
    )


def _query_zhipu_token_plan(api_key: str, timeout: int) -> dict[str, Any]:
    payload = _request_json(
        "GET",
        "https://api.z.ai/api/monitor/usage/quota/limit",
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept-Language": "en-US,en",
            "Accept": "application/json",
        },
        timeout=timeout,
        label="智谱 GLM Token Plan",
    )
    if payload.get("success") is False:
        raise BalanceQueryError(str(payload.get("msg") or payload.get("message") or "智谱 GLM 查询失败"))

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    token_limits: list[tuple[int, dict[str, Any]]] = []
    for item in data.get("limits") or []:
        if not isinstance(item, dict):
            continue
        limit_type = str(item.get("type") or "")
        if not limit_type.upper() == "TOKENS_LIMIT":
            continue
        reset_value = item.get("nextResetTime")
        reset_sort = _timestamp_sort_key(reset_value)
        token_limits.append((reset_sort, item))
    token_limits.sort(key=lambda pair: pair[0])

    rows: list[dict[str, str]] = []
    primary_remaining = None
    primary_used = None
    labels = ["5小时滚动窗口", "周额度"]
    for index, (_, item) in enumerate(token_limits):
        used_percent = _to_float(item.get("percentage"))
        remaining_percent = max(0.0, 100.0 - used_percent) if used_percent is not None else None
        if primary_remaining is None and remaining_percent is not None:
            primary_remaining = remaining_percent
            primary_used = used_percent
        rows.append(
            {
                "项目": labels[index] if index < len(labels) else f"Token 窗口 {index + 1}",
                "已用": _amount_text(used_percent, "%"),
                "剩余": _amount_text(remaining_percent, "%"),
                "重置时间": _format_reset_time(item.get("nextResetTime")),
            }
        )

    return _result(
        kind="plan",
        provider="智谱 GLM",
        title="智谱 GLM Token Plan 额度",
        amount=primary_remaining,
        unit="%",
        total=100.0 if primary_remaining is not None else None,
        used=primary_used,
        status="可用" if primary_remaining is None or primary_remaining > 0 else "额度已用完",
        source="智谱官方 Token Plan 接口",
        details={"level": data.get("level"), "raw": payload},
        rows=rows,
    )


def _query_minimax_token_plan(api_key: str, config: dict[str, Any], timeout: int) -> dict[str, Any]:
    group_id = str(config.get("group_id") or "").strip()
    query = f"?GroupId={group_id}" if group_id else ""
    endpoints = [
        f"https://api.minimaxi.com/v1/api/openplatform/coding_plan/remains{query}",
        f"https://api.minimax.io/v1/api/openplatform/coding_plan/remains{query}",
        f"https://www.minimax.io/v1/token_plan/remains{query}",
    ]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "MM-API-Source": "INTP-Study-Manager",
    }

    errors: list[str] = []
    payload: dict[str, Any] | None = None
    used_endpoint = ""
    for endpoint in endpoints:
        try:
            payload = _request_json(
                "GET",
                endpoint,
                headers=headers,
                timeout=timeout,
                label="MiniMax Token Plan 额度",
            )
            used_endpoint = endpoint
            break
        except BalanceQueryError as exc:
            errors.append(f"{endpoint}: {exc}")

    if payload is None:
        raise BalanceQueryError(
            "MiniMax Token Plan 查询失败。请确认你填的是 Token Plan Key / Credits Key，"
            "不是普通 Open Platform 按量付费 API Key。已尝试：" + "；".join(errors)
        )

    base_resp = payload.get("base_resp")
    if isinstance(base_resp, dict):
        status_code = _to_float(base_resp.get("status_code"))
        if status_code not in (None, 0):
            raise BalanceQueryError(str(base_resp.get("status_msg") or "MiniMax 返回错误"))

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    model_rows = data.get("model_remains") if isinstance(data.get("model_remains"), list) else []
    chat_record = _pick_minimax_chat_record(model_rows) if model_rows else data
    if not isinstance(chat_record, dict):
        chat_record = data

    interval_total = _pick_number(chat_record, ["current_interval_total_count", "currentIntervalTotalCount", "total", "quota", "limit"])
    interval_remaining = _pick_number(
        chat_record,
        [
            "current_interval_remain_count",
            "currentIntervalRemainCount",
            "remaining",
            "remain",
            "left",
            "current_interval_usage_count",
            "currentIntervalUsageCount",
        ],
    )
    # MiniMax 这个字段名容易误导；CC Switch 源码确认 usage_count 实际是剩余量。
    interval_used = _pick_number(chat_record, ["used", "usage", "used_count"])
    if interval_used is None and interval_total is not None and interval_remaining is not None:
        interval_used = max(0.0, interval_total - interval_remaining)

    weekly_total = _pick_number(chat_record, ["current_weekly_total_count", "currentWeeklyTotalCount", "weekly_total", "weeklyTotal"])
    weekly_remaining = _pick_number(
        chat_record,
        [
            "current_weekly_remain_count",
            "currentWeeklyRemainCount",
            "weekly_remaining",
            "weeklyRemaining",
            "current_weekly_usage_count",
            "currentWeeklyUsageCount",
        ],
    )
    weekly_used = _pick_number(chat_record, ["weekly_used", "weeklyUsed"])
    if weekly_used is None and weekly_total is not None and weekly_remaining is not None:
        weekly_used = max(0.0, weekly_total - weekly_remaining)

    rows = _minimax_usage_rows(model_rows)
    if weekly_total is not None or weekly_used is not None:
        rows.append(
            {
                "项目": "周额度",
                "模型": str(chat_record.get("model_name") or chat_record.get("modelName") or "MiniMax-M"),
                "已用": _number_text(weekly_used),
                "总额度": _number_text(weekly_total),
                "剩余": _number_text(weekly_remaining),
                "窗口": "weekly",
            }
        )

    return _result(
        kind="plan",
        provider="MiniMax",
        title="MiniMax Token Plan / Credits 额度",
        amount=interval_remaining,
        unit="次",
        total=interval_total,
        used=interval_used,
        status="可用" if interval_remaining is None or interval_remaining > 0 else "额度已用完",
        source="MiniMax 官方 Token Plan 接口",
        details={
            "endpoint": used_endpoint,
            "说明": "Token Plan 的文本模型通常是 5 小时滚动窗口；非文本模型通常是日额度。普通按量付费余额需在 MiniMax 控制台 Billing > Balance 查看。",
            "raw": payload,
        },
        rows=rows,
    )


def _query_newapi_user(base_url: str, access_token: str, config: dict[str, Any], timeout: int) -> dict[str, Any]:
    origin = _origin(base_url)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    user_id = str(config.get("user_id") or "").strip()
    if user_id:
        headers["New-Api-User"] = user_id

    errors: list[str] = []
    payload: dict[str, Any] | None = None
    used_endpoint = ""
    for endpoint in ["/api/user/self", "/api/data/self"]:
        try:
            payload = _request_json(
                "GET",
                f"{origin}{endpoint}",
                headers=headers,
                timeout=timeout,
                label=f"New API 用户额度 {endpoint}",
            )
            used_endpoint = endpoint
            break
        except BalanceQueryError as exc:
            errors.append(f"{endpoint}: {exc}")

    if payload is None:
        raise BalanceQueryError("New API / One API 用户额度查询失败：" + "；".join(errors))

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if payload.get("success") is False:
        raise BalanceQueryError(str(payload.get("message") or "New API 查询失败"))
    quota_unit = _to_float(config.get("quota_unit")) or 500000.0
    remaining_quota = _to_float(_first_path(data, ["quota", "remain_quota", "remaining_quota", "available_quota"]))
    used_quota = _to_float(_first_path(data, ["used_quota", "used", "used_amount"]))
    total_quota = _to_float(_first_path(data, ["total_quota", "total", "quota_limit"]))

    remaining = remaining_quota / quota_unit if remaining_quota is not None else _to_float(
        _first_path(data, ["balance", "available_balance", "remaining", "amount"])
    )
    used = used_quota / quota_unit if used_quota is not None else None
    total = total_quota / quota_unit if total_quota is not None else None
    if total is None and remaining is not None and used is not None:
        total = remaining + used
    return _result(
        kind="wallet",
        provider="New API / One API",
        title="New API 用户额度",
        amount=remaining,
        unit="USD",
        total=total,
        used=used,
        source="远程用户接口",
        details={
            "endpoint": used_endpoint,
            **{key: data.get(key) for key in ["username", "display_name", "group", "status", "quota", "used_quota"] if key in data},
        },
    )


def _query_openai_plan(access_token: str, config: dict[str, Any], timeout: int) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "INTP-Study-Manager",
    }
    account_id = str(config.get("account_id") or "").strip()
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    payload = _request_json(
        "GET",
        "https://chatgpt.com/backend-api/wham/usage",
        headers=headers,
        timeout=timeout,
        label="ChatGPT / Codex Plan 配额",
    )
    rate_limit = payload.get("rate_limit") if isinstance(payload.get("rate_limit"), dict) else {}
    rows = []
    primary_remaining = None
    for key, label in [("primary_window", "主窗口"), ("secondary_window", "周/月窗口")]:
        window = rate_limit.get(key)
        if not isinstance(window, dict):
            continue
        used_percent = _to_float(window.get("used_percent"))
        remaining_percent = max(0.0, 100.0 - used_percent) if used_percent is not None else None
        if primary_remaining is None and remaining_percent is not None:
            primary_remaining = remaining_percent
        rows.append(
            {
                "窗口": label,
                "已用": f"{used_percent:.0f}%" if used_percent is not None else "未知",
                "剩余": f"{remaining_percent:.0f}%" if remaining_percent is not None else "未知",
                "重置时间": _format_timestamp(window.get("reset_at")),
            }
        )
    plan = str(payload.get("plan_type") or payload.get("account_plan") or "unknown")
    status = "受限" if rate_limit.get("limit_reached") else "可用"
    return _result(
        kind="plan",
        provider="ChatGPT / Codex",
        title=f"官方账号 Plan 配额（{plan}）",
        amount=primary_remaining,
        unit="%",
        total=100.0 if primary_remaining is not None else None,
        used=100.0 - primary_remaining if primary_remaining is not None else None,
        status=status,
        source="远程账号配额接口",
        details={
            "email": payload.get("email"),
            "plan": plan,
            "allowed": rate_limit.get("allowed", True),
            "limit_reached": rate_limit.get("limit_reached", False),
            "credits": payload.get("credits"),
        },
        rows=rows,
    )


def _query_generic_wallet(base_url: str, api_key: str, config: dict[str, Any], timeout: int) -> dict[str, Any]:
    origin = _origin(base_url)
    endpoint = str(config.get("generic_path") or "/user/balance")
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    payload = _request_json(
        "GET",
        origin + endpoint,
        headers=_bearer_headers(api_key),
        timeout=timeout,
        label="通用钱包余额",
    )
    amount = _first_path(
        payload,
        [
            "balance",
            "data.balance",
            "total_balance",
            "data.total_balance",
            "remaining",
            "data.remaining",
            "total_available",
            "data.total_available",
            "available",
            "data.available",
        ],
    )
    total = _to_float(_first_path(payload, ["total", "data.total", "total_granted", "data.total_granted"]))
    used = _to_float(_first_path(payload, ["used", "data.used", "total_used", "data.total_used"]))
    unit = str(_first_path(payload, ["currency", "data.currency", "unit", "data.unit"]) or config.get("unit_value") or "USD")
    return _result(
        kind="wallet",
        provider="通用钱包接口",
        title="通用钱包余额",
        amount=_to_float(amount),
        unit=unit,
        total=total,
        used=used,
        source="远程余额接口",
        details=payload,
    )


def _query_credit_grants(base_url: str, api_key: str, timeout: int) -> dict[str, Any]:
    origin = _origin(base_url)
    payload = _request_json(
        "GET",
        f"{origin}/dashboard/billing/credit_grants",
        headers=_bearer_headers(api_key),
        timeout=timeout,
        label="OpenAI 兼容 billing 额度",
    )
    amount = _to_float(_first_path(payload, ["total_available", "data.total_available", "remaining"]))
    total = _to_float(_first_path(payload, ["total_granted", "data.total_granted", "total"]))
    used = _to_float(_first_path(payload, ["total_used", "data.total_used", "used"]))
    return _result(
        kind="wallet",
        provider="OpenAI 兼容代理",
        title="OpenAI 兼容 billing 额度",
        amount=amount,
        unit="USD",
        total=total,
        used=used,
        status="可用" if amount is None or amount > 0 else "余额不足",
        source="远程 billing 接口",
        details=payload,
    )


def _query_auto_wallet(
    provider: dict[str, Any],
    credential: str | None,
    config: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    base_url = _base_url(provider, config)
    key = _resolve_credential(provider, credential, config)
    errors: list[str] = []
    attempts = [
        ("CC Switch New API /api/user/self", lambda: _query_newapi_user(base_url, key, config, timeout)),
        ("通用 /user/balance", lambda: _query_generic_wallet(base_url, key, config, timeout)),
        ("OpenAI 兼容 /dashboard/billing/credit_grants", lambda: _query_credit_grants(base_url, key, timeout)),
    ]
    for label, query in attempts:
        try:
            result = query()
        except BalanceQueryError as exc:
            errors.append(f"{label}: {exc}")
            continue
        result["source"] = f"自动探测：{result.get('source') or label}"
        return result

    raise BalanceQueryError(
        "自动探测远程余额接口失败。已尝试："
        + "；".join(errors)
        + "。Sub2API / 环城网安这类网关如果只给模型调用 Key，通常需要改填管理端 Access Token。"
        + "如果供应商有专用余额接口，请在查询方式里选择“自定义 HTTP JSON”并填写接口路径。"
    )


def _query_custom_http(
    provider: dict[str, Any],
    credential: str,
    config: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    base_url = _base_url(provider, config)
    origin = _origin(base_url) if base_url else ""
    context = {
        "apiKey": credential,
        "accessToken": credential,
        "baseUrl": base_url.rstrip("/"),
        "origin": origin,
        "model": str(provider.get("model") or ""),
        "accountId": str(config.get("account_id") or ""),
        "userId": str(config.get("user_id") or ""),
    }
    url = _render_template(str(config.get("custom_url") or ""), context)
    if not url:
        raise BalanceQueryError("自定义查询 URL 不能为空。")
    method = str(config.get("custom_method") or "GET").upper()
    headers = _parse_headers(config.get("custom_headers_json"), context)
    if credential and not any(key.lower() == "authorization" for key in headers):
        headers["Authorization"] = f"Bearer {credential}"
    body = _render_template(str(config.get("custom_body") or ""), context)
    payload = _request_json(method, url, headers=headers, body=body or None, timeout=timeout, label="自定义余额查询")

    remaining = _to_float(_get_path(payload, str(config.get("remaining_path") or "")))
    total = _to_float(_get_path(payload, str(config.get("total_path") or "")))
    used = _to_float(_get_path(payload, str(config.get("used_path") or "")))
    unit = str(_get_path(payload, str(config.get("unit_path") or "")) or config.get("unit_value") or "")
    plan_name = str(_get_path(payload, str(config.get("plan_name_path") or "")) or "自定义查询")
    status = str(_get_path(payload, str(config.get("status_path") or "")) or "可用")
    reset = _get_path(payload, str(config.get("reset_path") or ""))
    return _result(
        kind="custom",
        provider=provider.get("name") or "自定义 Provider",
        title=plan_name,
        amount=remaining,
        unit=unit,
        total=total,
        used=used,
        status=status,
        source="自定义远程接口",
        details={"reset": reset, "raw": payload},
    )


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout: int,
    label: str,
    body: str | None = None,
) -> dict[str, Any]:
    try:
        response = requests.request(method, url, headers=headers, data=body, timeout=timeout)
    except requests.RequestException as exc:
        raise BalanceQueryError(f"{label} 请求失败：{exc}") from exc
    if response.status_code in {401, 403}:
        raise BalanceQueryError(f"{label} 鉴权失败（HTTP {response.status_code}）。请检查 API Key / Access Token。")
    if response.status_code >= 400:
        raise BalanceQueryError(f"{label} 返回 HTTP {response.status_code}：{_compact(response.text)}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise BalanceQueryError(f"{label} 没有返回 JSON：{_compact(response.text)}") from exc
    if not isinstance(payload, dict):
        raise BalanceQueryError(f"{label} 返回格式不是 JSON 对象。")
    return payload


def _result(
    *,
    kind: str,
    provider: str,
    title: str,
    amount: float | None,
    unit: str,
    total: float | None = None,
    used: float | None = None,
    status: str = "可用",
    source: str,
    details: dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "provider": provider,
        "title": title,
        "amount": amount,
        "amount_text": _amount_text(amount, unit),
        "unit": unit,
        "total": total,
        "used": used,
        "status": status,
        "source": source,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "details": details or {},
        "rows": rows or [],
    }


def _detect_wallet_query_type(base_url: str) -> str:
    url = (base_url or "").lower()
    host = _hostname(base_url)
    if "api.kimi.com/coding" in url:
        return "kimi_token_plan"
    if "bigmodel.cn" in host or "api.z.ai" in host:
        return "zhipu_token_plan"
    if host in {"api.minimaxi.com", "api.minimax.io", "api.minimax.chat", "platform.minimax.io"}:
        return "minimax_token_plan"
    if "deepseek.com" in host:
        return "deepseek_wallet"
    if "openrouter.ai" in host:
        return "openrouter_wallet"
    if "siliconflow.cn" in host or "siliconflow.com" in host:
        return "siliconflow_wallet"
    if "stepfun.com" in host or "stepfun.ai" in host:
        return "stepfun_wallet"
    if "novita.ai" in host:
        return "novita_wallet"
    if "oneapi" in host or "newapi" in host:
        return "newapi_user"
    return ""


def _pick_minimax_chat_record(model_rows: list[Any]) -> dict[str, Any] | None:
    records = [item for item in model_rows if isinstance(item, dict)]
    if not records:
        return None
    for record in records:
        name = str(record.get("model_name") or record.get("modelName") or "").lower()
        total = _pick_number(record, ["current_interval_total_count", "currentIntervalTotalCount"])
        if name.startswith("minimax-m") and total is not None and total > 0:
            return record
    for record in records:
        total = _pick_number(record, ["current_interval_total_count", "currentIntervalTotalCount"])
        if total is not None and total > 0:
            return record
    return records[0]


def _minimax_usage_rows(model_rows: list[Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in model_rows:
        if not isinstance(item, dict):
            continue
        interval_total = _pick_number(item, ["current_interval_total_count", "currentIntervalTotalCount"])
        interval_remaining = _pick_number(
            item,
            [
                "current_interval_remain_count",
                "currentIntervalRemainCount",
                "remaining",
                "remain",
                "left",
                "current_interval_usage_count",
                "currentIntervalUsageCount",
            ],
        )
        interval_used = _pick_number(item, ["used", "usage", "used_count"])
        if interval_used is None and interval_total is not None and interval_remaining is not None:
            interval_used = max(0.0, interval_total - interval_remaining)
        daily_total = _pick_number(item, ["daily_total_count", "dailyTotalCount", "current_daily_total_count", "currentDailyTotalCount"])
        daily_remaining = _pick_number(item, ["daily_remaining_count", "dailyRemainingCount", "current_daily_remain_count", "currentDailyRemainCount"])
        daily_used = _pick_number(item, ["daily_used", "dailyUsed"])
        if daily_used is None and daily_total is not None and daily_remaining is not None:
            daily_used = max(0.0, daily_total - daily_remaining)
        model_name = str(item.get("model_name") or item.get("modelName") or item.get("model") or "未知模型")
        if interval_total is not None or interval_used is not None:
            rows.append(
                {
                    "项目": "5小时滚动窗口",
                    "模型": model_name,
                    "已用": _number_text(interval_used),
                    "总额度": _number_text(interval_total),
                    "剩余": _number_text(interval_remaining),
                    "窗口": "5h",
                }
            )
        if daily_total is not None or daily_used is not None:
            rows.append(
                {
                    "项目": "日额度",
                    "模型": model_name,
                    "已用": _number_text(daily_used),
                    "总额度": _number_text(daily_total),
                    "剩余": _number_text(daily_remaining),
                    "窗口": "daily",
                }
            )
    return rows


def _pick_number(record: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        amount = _to_float(record.get(key))
        if amount is not None:
            return amount
    return None


def _number_text(value: float | None) -> str:
    if value is None:
        return "未知"
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _resolve_credential(provider: dict[str, Any], credential: str | None, config: dict[str, Any]) -> str:
    key = str(credential or "").strip()
    if not key:
        env_name = str(config.get("credential_env") or provider.get("api_key_env") or "").strip()
        key = (os.getenv(env_name) or "").strip() if env_name else ""
    if not key:
        raise BalanceQueryError("没有可用凭据。请粘贴 API Key / Access Token，或先解锁本地加密 API Key。")
    return key


def _resolve_access_token(provider: dict[str, Any], credential: str | None, config: dict[str, Any]) -> str:
    token = str(credential or "").strip()
    if not token:
        env_name = str(config.get("access_token_env") or config.get("credential_env") or provider.get("api_key_env") or "").strip()
        token = (os.getenv(env_name) or "").strip() if env_name else ""
    if not token:
        raise BalanceQueryError("没有可用 Access Token。Plan / New API 查询需要手动粘贴或从加密密钥库解锁。")
    return token


def _bearer_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _base_url(provider: dict[str, Any], config: dict[str, Any]) -> str:
    return str(config.get("base_url") or provider.get("base_url") or "").strip()


def _origin(base_url: str) -> str:
    value = base_url.strip()
    if not value:
        raise BalanceQueryError("Base URL 不能为空。")
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if not parsed.scheme or not parsed.netloc:
        raise BalanceQueryError("Base URL 不合法，无法判断远程查询地址。")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _hostname(base_url: str) -> str:
    try:
        return (urlparse(base_url if "://" in base_url else f"https://{base_url}").hostname or "").lower()
    except Exception:
        return ""


def _timeout(config: dict[str, Any]) -> int:
    try:
        return max(2, min(30, int(config.get("timeout") or 10)))
    except (TypeError, ValueError):
        return 10


def _parse_headers(raw: Any, context: dict[str, str]) -> dict[str, str]:
    if not str(raw or "").strip():
        return {"Accept": "application/json"}
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise BalanceQueryError(f"自定义请求头 JSON 不合法：{exc}") from exc
    if not isinstance(value, dict):
        raise BalanceQueryError("自定义请求头必须是 JSON 对象。")
    return {str(key): _render_template(str(val), context) for key, val in value.items()}


def _render_template(value: str, context: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return str(context.get(key, ""))

    return re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", repl, value or "")


def _get_path(payload: Any, path: str) -> Any:
    if not path:
        return None
    current = payload
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _first_path(payload: dict[str, Any], paths: list[str]) -> Any:
    for path in paths:
        value = _get_path(payload, path)
        if value not in (None, ""):
            return value
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(data: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        amount = _to_float(data.get(key))
        if amount is not None:
            return amount
    return None


def _amount_text(value: float | None, unit: str) -> str:
    if value is None:
        return "未知"
    if unit == "%":
        return f"{value:.0f}%"
    if unit == "次":
        return f"{value:.0f} 次"
    if unit.upper() == "USD":
        return f"${value:.4f}" if value < 1 else f"${value:.2f}"
    if unit == "tokens":
        return f"{value:.0f} tokens"
    return f"{value:.4f} {unit}".strip() if value < 1 else f"{value:.2f} {unit}".strip()


def _format_timestamp(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return "未知"
    if timestamp <= 0:
        return "未知"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _format_reset_time(value: Any) -> str:
    if value in (None, ""):
        return "未知"
    if isinstance(value, str) and not value.strip().isdigit():
        return value
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return str(value)
    if timestamp <= 0:
        return "未知"
    if timestamp >= 1_000_000_000_000:
        timestamp = timestamp // 1000
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _timestamp_sort_key(value: Any) -> int:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return 9_223_372_036_854_775_807
    return timestamp if timestamp > 0 else 9_223_372_036_854_775_807


def _compact(text: str, limit: int = 500) -> str:
    normalized = " ".join(str(text or "").split())
    return normalized[:limit] + ("..." if len(normalized) > limit else "")
