from __future__ import annotations

import streamlit as st

from db import fetch_all, fetch_one
from services.prompt_service import format_knowledge_card, format_study_record, render_template


def render() -> None:
    st.title("闭卷测试 Prompt")
    st.caption("这里不接入 OpenAI API，只生成可复制给 ChatGPT 的提问 Prompt。")

    tab_study, tab_card, tab_daily = st.tabs(["按学习记录生成", "按知识点生成", "每日复盘 Prompt"])

    with tab_study:
        records = fetch_all("SELECT * FROM study_sessions ORDER BY date DESC, id DESC")
        if not records:
            st.info("暂无学习记录。")
        else:
            selected_id = st.selectbox(
                "选择学习记录",
                [r["id"] for r in records],
                format_func=lambda item_id: _record_label(records, item_id),
            )
            record = fetch_one("SELECT * FROM study_sessions WHERE id = ?", (selected_id,))
            prompt = render_template(
                "closed_book_quiz.md",
                {"study_content": format_study_record(record or {})},
            )
            st.code(prompt, language="markdown")
            st.caption("Streamlit 代码块右上角有复制按钮；也可以手动全选复制。")

    with tab_card:
        cards = fetch_all("SELECT * FROM knowledge_cards ORDER BY created_at DESC, id DESC")
        if not cards:
            st.info("暂无知识点卡片。")
        else:
            selected_id = st.selectbox(
                "选择知识点卡片",
                [c["id"] for c in cards],
                format_func=lambda item_id: _card_label(cards, item_id),
            )
            card = fetch_one("SELECT * FROM knowledge_cards WHERE id = ?", (selected_id,))
            prompt = render_template(
                "closed_book_quiz.md",
                {"study_content": format_knowledge_card(card or {})},
            )
            st.code(prompt, language="markdown")

    with tab_daily:
        records = fetch_all("SELECT * FROM study_sessions ORDER BY date DESC, id DESC")
        if not records:
            st.info("暂无学习记录。")
        else:
            selected_id = st.selectbox(
                "选择复盘用学习记录",
                [r["id"] for r in records],
                format_func=lambda item_id: _record_label(records, item_id),
                key="daily_review_record",
            )
            record = fetch_one("SELECT * FROM study_sessions WHERE id = ?", (selected_id,))
            prompt = render_template(
                "daily_review.md",
                {"study_record": format_study_record(record or {})},
            )
            st.code(prompt, language="markdown")


def _record_label(records: list[dict], record_id: int) -> str:
    record = next(item for item in records if item["id"] == record_id)
    return f"{record['date']} · {record['subject']} · {record['title']}"


def _card_label(cards: list[dict], card_id: int) -> str:
    card = next(item for item in cards if item["id"] == card_id)
    return f"{card['subject']} · {card['topic']} · {card['mastery']}%"

