from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db import execute, fetch_all, fetch_one, insert_and_get_id
from services.review_service import ensure_initial_review_tasks


def render() -> None:
    st.title("知识点卡片")
    st.caption("每张卡片都按“三层模型”组织：一句话解释、公式 / 逻辑推导、典型题 / 应用。")

    sessions = fetch_all("SELECT id, date, subject, title FROM study_sessions ORDER BY date DESC, id DESC")
    session_options = [None] + [s["id"] for s in sessions]

    with st.form("add_knowledge_card"):
        st.subheader("创建知识点卡片")
        cols = st.columns(3)
        subject = cols[0].text_input("科目")
        topic = cols[1].text_input("知识点")
        mastery = cols[2].slider("掌握度", 0, 100, 60)
        core_question = st.text_area("核心问题", placeholder="这个知识点想解决什么问题？")
        one_sentence = st.text_area("一句话解释")
        logic_or_formula = st.text_area("公式 / 逻辑推导")
        application = st.text_area("典型题 / 应用场景")
        need_review = st.checkbox("创建 1-3-7-14 复习任务", value=True)
        source_session_id = st.selectbox(
            "关联学习记录（可选）",
            session_options,
            format_func=lambda item: "不关联" if item is None else _session_label(sessions, item),
        )
        submitted = st.form_submit_button("保存知识点卡片")

    if submitted:
        if not subject.strip() or not topic.strip() or not one_sentence.strip():
            st.error("科目、知识点、一句话解释不能为空。")
        else:
            knowledge_id = insert_and_get_id(
                """
                INSERT INTO knowledge_cards (
                    subject, topic, core_question, one_sentence, logic_or_formula,
                    application, mastery, need_review, source_session_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subject.strip(),
                    topic.strip(),
                    core_question.strip(),
                    one_sentence.strip(),
                    logic_or_formula.strip(),
                    application.strip(),
                    mastery,
                    int(need_review),
                    source_session_id,
                ),
            )
            if need_review:
                ensure_initial_review_tasks(knowledge_id, date.today())
            st.success("知识点卡片已保存，复习任务已按 1-3-7-14 生成。")

    st.divider()
    cards = fetch_all("SELECT * FROM knowledge_cards ORDER BY created_at DESC, id DESC")
    st.subheader("知识点列表")
    if not cards:
        st.info("暂无知识点卡片。")
        return

    subjects = sorted({item["subject"] for item in cards})
    selected_subject = st.selectbox("按科目筛选", ["全部"] + subjects)
    filtered = cards if selected_subject == "全部" else [c for c in cards if c["subject"] == selected_subject]
    st.dataframe(
        pd.DataFrame(filtered)[["id", "subject", "topic", "core_question", "mastery", "need_review"]],
        use_container_width=True,
        hide_index=True,
    )

    selected_id = st.selectbox(
        "查看 / 编辑知识点",
        [c["id"] for c in filtered],
        format_func=lambda item_id: f"#{item_id} - {next(c['topic'] for c in filtered if c['id'] == item_id)}",
    )
    card = fetch_one("SELECT * FROM knowledge_cards WHERE id = ?", (selected_id,))
    if not card:
        return

    left, right = st.columns([1.2, 1])
    with left:
        with st.form(f"edit_knowledge_card_{selected_id}"):
            st.subheader("编辑知识点")
            edit_subject = st.text_input("科目", value=card["subject"])
            edit_topic = st.text_input("知识点", value=card["topic"])
            edit_question = st.text_area("核心问题", value=card["core_question"] or "")
            edit_one = st.text_area("一句话解释", value=card["one_sentence"] or "")
            edit_logic = st.text_area("公式 / 逻辑推导", value=card["logic_or_formula"] or "")
            edit_app = st.text_area("典型题 / 应用场景", value=card["application"] or "")
            edit_mastery = st.slider("掌握度", 0, 100, int(card["mastery"]), key=f"card_mastery_{selected_id}")
            edit_need_review = st.checkbox("需要复习", value=bool(card["need_review"]))
            update_submitted = st.form_submit_button("更新知识点")
        if update_submitted:
            execute(
                """
                UPDATE knowledge_cards
                SET subject = ?, topic = ?, core_question = ?, one_sentence = ?,
                    logic_or_formula = ?, application = ?, mastery = ?, need_review = ?
                WHERE id = ?
                """,
                (
                    edit_subject.strip(),
                    edit_topic.strip(),
                    edit_question.strip(),
                    edit_one.strip(),
                    edit_logic.strip(),
                    edit_app.strip(),
                    edit_mastery,
                    int(edit_need_review),
                    selected_id,
                ),
            )
            if edit_need_review:
                ensure_initial_review_tasks(selected_id, card["created_at"])
            st.success("知识点已更新。")
            st.rerun()

    with right:
        st.subheader("关联复习计划")
        tasks = fetch_all(
            """
            SELECT review_date, review_stage, status, result
            FROM review_tasks
            WHERE knowledge_id = ?
            ORDER BY review_date ASC, id ASC
            """,
            (selected_id,),
        )
        if tasks:
            st.dataframe(pd.DataFrame(tasks), use_container_width=True, hide_index=True)
        else:
            st.caption("暂无复习任务。勾选需要复习并保存后会自动生成。")

        st.subheader("关联错题")
        mistakes = fetch_all(
            """
            SELECT cause_category, original_question, summary, created_at
            FROM mistakes
            WHERE knowledge_id = ? OR (subject = ? AND topic = ?)
            ORDER BY created_at DESC
            """,
            (selected_id, card["subject"], card["topic"]),
        )
        if mistakes:
            st.dataframe(pd.DataFrame(mistakes), use_container_width=True, hide_index=True)
        else:
            st.caption("暂无关联错题。")

        st.subheader("关联插问")
        branches = fetch_all(
            """
            SELECT ma.anchor_code, bq.question, bq.answer_summary, bq.understood
            FROM branch_questions bq
            JOIN mainline_anchors ma ON ma.id = bq.anchor_id
            WHERE bq.question LIKE ? OR bq.answer_summary LIKE ?
            ORDER BY bq.created_at DESC
            """,
            (f"%{card['topic']}%", f"%{card['topic']}%"),
        )
        if branches:
            st.dataframe(pd.DataFrame(branches), use_container_width=True, hide_index=True)
        else:
            st.caption("暂无关联插问。")


def _session_label(sessions: list[dict], session_id: int) -> str:
    session = next(item for item in sessions if item["id"] == session_id)
    return f"{session['date']} · {session['subject']} · {session['title']}"

