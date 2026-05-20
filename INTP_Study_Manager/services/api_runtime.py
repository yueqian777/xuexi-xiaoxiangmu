from __future__ import annotations

from typing import Any

import streamlit as st

from services.ai_service import DEFAULT_MODEL


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
