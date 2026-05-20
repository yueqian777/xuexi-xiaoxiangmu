from __future__ import annotations

import pandas as pd
import streamlit as st

from db import execute, fetch_all, fetch_one, insert_and_get_id
from services.review_service import ensure_initial_review_tasks


def render() -> None:
    st.title("探索停车场")
    st.caption("暂时不处理的扩展问题先停在这里，避免打断当前主线。")

    with st.form("add_parking_question"):
        st.subheader("添加临时问题")
        cols = st.columns(2)
        subject = cols[0].text_input("科目")
        source = cols[1].text_input("来源", placeholder="例如：学习登记 / M2 插问 / 错题")
        question = st.text_area("问题")
        submitted = st.form_submit_button("加入停车场")

    if submitted:
        if not question.strip():
            st.error("问题不能为空。")
        else:
            insert_and_get_id(
                "INSERT INTO parking_lot (subject, question, source) VALUES (?, ?, ?)",
                (subject.strip(), question.strip(), source.strip()),
            )
            st.success("问题已加入探索停车场。")

    questions = fetch_all("SELECT * FROM parking_lot ORDER BY created_at DESC, id DESC")
    st.divider()
    st.subheader("停车场列表")
    if not questions:
        st.info("暂无停车场问题。")
        return

    st.dataframe(
        pd.DataFrame(questions)[["id", "subject", "question", "source", "status", "created_at"]],
        use_container_width=True,
        hide_index=True,
    )

    selected_id = st.selectbox(
        "选择一个问题处理",
        [q["id"] for q in questions],
        format_func=lambda item_id: f"#{item_id} - {next(q['question'] for q in questions if q['id'] == item_id)[:40]}",
    )
    selected = fetch_one("SELECT * FROM parking_lot WHERE id = ?", (selected_id,))
    if not selected:
        return

    action = st.radio("处理方式", ["标记已解决", "转化为知识点卡片", "转化为插问"], horizontal=True)
    if action == "标记已解决":
        if st.button("标记为已解决"):
            execute("UPDATE parking_lot SET status = '已解决' WHERE id = ?", (selected_id,))
            st.success("已标记为解决。")
            st.rerun()

    elif action == "转化为知识点卡片":
        with st.form("convert_parking_to_card"):
            topic = st.text_input("知识点名称", value=selected["question"][:30])
            one_sentence = st.text_area("一句话解释", value=f"待补充：{selected['question']}")
            logic = st.text_area("公式 / 逻辑推导")
            application = st.text_area("典型题 / 应用场景")
            mastery = st.slider("掌握度", 0, 100, 50)
            need_review = st.checkbox("生成 1-3-7-14 复习任务", value=True)
            submitted = st.form_submit_button("转化为知识点")
        if submitted:
            knowledge_id = insert_and_get_id(
                """
                INSERT INTO knowledge_cards (
                    subject, topic, core_question, one_sentence, logic_or_formula,
                    application, mastery, need_review
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected["subject"] or "未分类",
                    topic.strip(),
                    selected["question"],
                    one_sentence.strip(),
                    logic.strip(),
                    application.strip(),
                    mastery,
                    int(need_review),
                ),
            )
            if need_review:
                ensure_initial_review_tasks(knowledge_id)
            execute("UPDATE parking_lot SET status = '已转知识点' WHERE id = ?", (selected_id,))
            st.success("已转化为知识点卡片。")
            st.rerun()

    else:
        sessions = fetch_all("SELECT id, date, subject, title FROM study_sessions ORDER BY date DESC, id DESC")
        anchors = fetch_all(
            """
            SELECT ma.id, ma.session_id, ma.anchor_code, ma.title, ss.date, ss.subject, ss.title AS session_title
            FROM mainline_anchors ma
            JOIN study_sessions ss ON ss.id = ma.session_id
            ORDER BY ss.date DESC, ma.order_index ASC, ma.id ASC
            """
        )
        if not sessions or not anchors:
            st.warning("需要先在“学习登记”创建记录，并在“主线与插问”创建主线锚点。")
        else:
            anchor_id = st.selectbox(
                "绑定主线锚点",
                [a["id"] for a in anchors],
                format_func=lambda item_id: _anchor_label(anchors, item_id),
            )
            anchor = next(a for a in anchors if a["id"] == anchor_id)
            if st.button("转化为插问"):
                insert_and_get_id(
                    """
                    INSERT INTO branch_questions (
                        session_id, anchor_id, question, need_review
                    )
                    VALUES (?, ?, ?, 1)
                    """,
                    (anchor["session_id"], anchor_id, selected["question"]),
                )
                execute("UPDATE parking_lot SET status = '已转插问' WHERE id = ?", (selected_id,))
                st.success(f"已转化为插问。现在回到主线 {anchor['anchor_code']}。")
                st.rerun()


def _anchor_label(anchors: list[dict], anchor_id: int) -> str:
    anchor = next(item for item in anchors if item["id"] == anchor_id)
    return f"{anchor['date']} · {anchor['subject']} · {anchor['session_title']} · {anchor['anchor_code']} {anchor['title']}"

