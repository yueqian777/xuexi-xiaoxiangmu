from __future__ import annotations

import json
from typing import Any

import streamlit as st

from db import execute, fetch_one
from services.ai_service import DEFAULT_MODEL

DEFAULT_API_SETTING_KEY = "default_api_config"


def provider_model_state_key(provider_id: int) -> str:
    return f"api_model_provider_{provider_id}"


def ensure_provider_model(provider: dict[str, Any]) -> str:
    provider_id = int(provider["id"])
    key = provider_model_state_key(provider_id)
    if key not in st.session_state:
        st.session_state[key] = provider.get("model") or DEFAULT_MODEL
    model = str(st.session_state.get(key) or provider.get("model") or DEFAULT_MODEL).strip()
    st.session_state[key] = model
    return model


def set_active_provider(provider_id: int, model: str) -> None:
    st.session_state["active_api_provider_id"] = provider_id
    st.session_state["active_api_model"] = model.strip() or DEFAULT_MODEL


def get_default_api_config() -> dict[str, Any]:
    row = fetch_one("SELECT value FROM app_settings WHERE key = ?", (DEFAULT_API_SETTING_KEY,))
    if not row:
        return {}
    try:
        data = json.loads(row["value"])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_default_api_config(provider_id: int, model: str) -> None:
    payload = json.dumps(
        {"provider_id": int(provider_id), "model": model.strip() or DEFAULT_MODEL},
        ensure_ascii=False,
    )
    execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, datetime('now', 'localtime'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (DEFAULT_API_SETTING_KEY, payload),
    )


def default_provider_id_from_config(providers: list[dict[str, Any]]) -> int | None:
    if not providers:
        return None
    provider_ids = {int(provider["id"]) for provider in providers}
    config = get_default_api_config()
    try:
        provider_id = int(config.get("provider_id", 0))
    except (TypeError, ValueError):
        provider_id = 0
    return provider_id if provider_id in provider_ids else None


def ensure_active_provider(providers: list[dict[str, Any]]) -> tuple[int | None, str]:
    if not providers:
        return None, DEFAULT_MODEL

    provider_ids = {int(provider["id"]) for provider in providers}
    try:
        active_id = int(st.session_state.get("active_api_provider_id", 0))
    except (TypeError, ValueError):
        active_id = 0
    if active_id in provider_ids:
        provider = next(item for item in providers if int(item["id"]) == int(active_id))
        model = str(st.session_state.get("active_api_model") or ensure_provider_model(provider)).strip()
        set_active_provider(int(active_id), model)
        return int(active_id), model

    default_id = default_provider_id_from_config(providers)
    if default_id is None:
        default_id = int(providers[0]["id"])
    provider = next(item for item in providers if int(item["id"]) == default_id)
    config = get_default_api_config()
    model = str(config.get("model") or ensure_provider_model(provider) or provider.get("model") or DEFAULT_MODEL)
    ensure_provider_model(provider)
    st.session_state[provider_model_state_key(default_id)] = model.strip() or DEFAULT_MODEL
    set_active_provider(default_id, model)
    return default_id, model
