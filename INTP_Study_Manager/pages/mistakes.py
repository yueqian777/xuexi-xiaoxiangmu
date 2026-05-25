from __future__ import annotations

import pandas as pd
import streamlit as st

from db import fetch_all, insert_and_get_id
from models import ERROR_CAUSE_CATEGORIES
from services.auth_service import require_login
from services.review_service import ensure_initial_review_tasks
from services.stats_service import mistake_cause_counts


def render() -> None:
    user = require_login()
    st.title("错因本")
    st.caption("记录错题不是为了存档，而是为了识别下次要警惕的信号。")

    cards = fetch_all("SELECT id, subject, topic FROM knowledge_cards WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user.id,))
    card_options = [None] + [c["id"] for c in cards]

    with st.form("add_mistake"):
        st.subheader("添加错题 / 错误回答")
        cols = st.columns(2)
        subject = cols[0].text_input("科目")
        topic = cols[1].text_input("知识点")
        knowledge_id = st.selectbox(
            "关联知识点卡片（可选）",
            card_options,
            format_func=lambda item: "不关联" if item is None else _card_label(cards, item),
        )
        original_question = st.text_area("原题 / 原问题")
        my_wrong_answer = st.text_area("我的错误回答")
        correct_idea = st.text_area("正确思路")
        cause_category = st.selectbox("错因分类", ERROR_CAUSE_CATEGORIES)
        summary = st.text_area("一句话总结")
        warning_signal = st.text_area("下次看到什么信号要警惕")
        add_to_review = st.checkbox("加入复习队列", value=True)
        submitted = st.form_submit_button("保存错因")

    if submitted:
        if knowledge_id is not None:
            card = next(c for c in cards if c["id"] == knowledge_id)
            subject = subject.strip() or card["subject"]
            topic = topic.strip() or card["topic"]
        if not subject.strip() or not topic.strip() or not original_question.strip() or not correct_idea.strip():
            st.error("科目、知识点、原题 / 原问题、正确思路不能为空。")
        else:
            insert_and_get_id(
                """
                INSERT INTO mistakes (
                    user_id, subject, topic, knowledge_id, original_question, my_wrong_answer,
                    correct_idea, cause_category, warning_signal, summary, add_to_review
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    subject.strip(),
                    topic.strip(),
                    knowledge_id,
                    original_question.strip(),
                    my_wrong_answer.strip(),
                    correct_idea.strip(),
                    cause_category,
                    warning_signal.strip(),
                    summary.strip(),
                    int(add_to_review),
                ),
            )
            if add_to_review and knowledge_id is not None:
                ensure_initial_review_tasks(knowledge_id, user_id=user.id)
            st.success("错因已保存。")

    st.divider()
    mistakes = fetch_all("SELECT * FROM mistakes WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user.id,))
    st.subheader("错因记录")
    if not mistakes:
        st.info("暂无错因记录。")
        return

    subjects = sorted({m["subject"] for m in mistakes})
    selected_subject = st.selectbox("按科目筛选", ["全部"] + subjects)
    filtered = mistakes if selected_subject == "全部" else [m for m in mistakes if m["subject"] == selected_subject]
    st.dataframe(
        pd.DataFrame(filtered)[
            ["id", "subject", "topic", "cause_category", "summary", "warning_signal", "created_at"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("高频错因统计")
    counts = mistake_cause_counts(None if selected_subject == "全部" else selected_subject, user_id=user.id)
    if counts:
        chart_df = pd.DataFrame(counts).set_index("cause_category")
        st.bar_chart(chart_df)
    else:
        st.caption("当前筛选条件下暂无统计。")


def _card_label(cards: list[dict], card_id: int) -> str:
    card = next(item for item in cards if item["id"] == card_id)
    return f"{card['subject']} · {card['topic']}"
