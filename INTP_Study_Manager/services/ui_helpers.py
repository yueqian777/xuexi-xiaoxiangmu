from __future__ import annotations

import streamlit as st


def render_workbench_header(title: str, caption: str) -> None:
    st.title(title)
    st.caption(caption)


def set_navigation_target(section_id: str, page_id: str) -> None:
    st.session_state["app_selected_section_id"] = section_id
    st.session_state["app_selected_page_id"] = page_id
    st.session_state["app_selected_page_section_id"] = section_id
