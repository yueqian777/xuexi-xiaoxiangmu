from __future__ import annotations

import json
from typing import Any

import streamlit as st

from db import execute, fetch_one
from services.ai_service import DEFAULT_MODEL
from services.auth_service import require_login

DEFAULT_API_SETTING_KEY = "default_api_config"


def _user_setting_key(key: str, user_id: int) -> str:
    return f"user:{user_id}:{key}"


def provider_model_state_key(provider_key: str) -> str:
    return f"api_model_provider_{provider_key}"


def ensure_provider_model(provider: dict[str, Any]) -> str:
    provider_key = str(provider["provider_key"])
    key = provider_model_state_key(provider_key)
    default_model = str(provider.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if key not in st.session_state:
        st.session_state[key] = default_model
        return default_model
    return str(st.session_state.get(key) or default_model).strip() or default_model


def set_active_provider(provider_key: str, model: str) -> None:
    st.session_state["active_api_provider_key"] = provider_key
    st.session_state["active_api_model"] = model.strip() or DEFAULT_MODEL


def get_default_api_config() -> dict[str, Any]:
    user = require_login()
    user_key = _user_setting_key(DEFAULT_API_SETTING_KEY, user.id)
    row = fetch_one("SELECT value FROM app_settings WHERE key = ?", (user_key,))
    if row:
        return _decode_default_api_config(row["value"])

    legacy_row = fetch_one("SELECT value FROM app_settings WHERE key = ?", (DEFAULT_API_SETTING_KEY,))
    if not legacy_row:
        return {}
    config = _decode_default_api_config(legacy_row["value"])
    if config:
        _save_default_api_config_for_user(user_key, user.id, config)
    return config


def _decode_default_api_config(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_default_api_config(provider_key: str, model: str) -> None:
    user = require_login()
    payload = json.dumps(
        {"provider_key": provider_key, "model": model.strip() or DEFAULT_MODEL},
        ensure_ascii=False,
    )
    _save_default_api_config_for_user(_user_setting_key(DEFAULT_API_SETTING_KEY, user.id), user.id, json.loads(payload))


def _save_default_api_config_for_user(key: str, user_id: int, config: dict[str, Any]) -> None:
    payload = json.dumps(config, ensure_ascii=False)
    execute(
        """
        INSERT INTO app_settings (key, user_id, value, updated_at)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(key) DO UPDATE SET
            user_id = excluded.user_id,
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, user_id, payload),
    )


def default_provider_key_from_config(providers: list[dict[str, Any]]) -> str | None:
    if not providers:
        return None
    provider_keys = {str(provider["provider_key"]) for provider in providers}
    config = get_default_api_config()
    provider_key = str(config.get("provider_key") or "")
    return provider_key if provider_key in provider_keys else None


def ensure_active_provider(providers: list[dict[str, Any]]) -> tuple[str | None, str]:
    if not providers:
        return None, DEFAULT_MODEL

    provider_keys = {str(provider["provider_key"]) for provider in providers}
    active_key = str(st.session_state.get("active_api_provider_key") or "")
    if active_key in provider_keys:
        provider = next(item for item in providers if str(item["provider_key"]) == active_key)
        model = str(st.session_state.get("active_api_model") or ensure_provider_model(provider)).strip()
        set_active_provider(active_key, model)
        return active_key, model

    default_key = default_provider_key_from_config(providers)
    if default_key is None:
        default_key = str(providers[0]["provider_key"])
    provider = next(item for item in providers if str(item["provider_key"]) == default_key)
    config = get_default_api_config()
    model = str(config.get("model") or ensure_provider_model(provider) or provider.get("model") or DEFAULT_MODEL)
    ensure_provider_model(provider)
    st.session_state[provider_model_state_key(default_key)] = model.strip() or DEFAULT_MODEL
    set_active_provider(default_key, model)
    return default_key, model
