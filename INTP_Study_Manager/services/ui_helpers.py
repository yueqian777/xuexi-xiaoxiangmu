from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import streamlit as st


PENDING_NAVIGATION_STATE_KEY = "app_pending_navigation_target"


def render_workbench_header(title: str, caption: str) -> None:
    st.title(title)
    st.caption(caption)


def set_navigation_target(section_id: str, page_id: str) -> None:
    st.session_state[PENDING_NAVIGATION_STATE_KEY] = {
        "section_id": section_id,
        "page_id": page_id,
    }


def pop_navigation_target(
    state: MutableMapping[str, Any] | None = None,
) -> tuple[str, str] | None:
    state = st.session_state if state is None else state
    target = state.pop(PENDING_NAVIGATION_STATE_KEY, None)
    if not isinstance(target, dict):
        return None

    section_id = target.get("section_id")
    page_id = target.get("page_id")
    if not isinstance(section_id, str) or not isinstance(page_id, str):
        return None
    return section_id, page_id
