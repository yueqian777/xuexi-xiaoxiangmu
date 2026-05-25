from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from db import execute, fetch_all, fetch_one, insert_and_get_id
from services.auth_service import require_login
from services.review_service import create_initial_review_tasks


def _date_value(value: str | None) -> date:
    if not value:
        return date.today()
    return datetime.fromisoformat(value[:10]).date()


def render() -> None:
    user = require_login()
    st.title("学习登记")
    st.caption("记录“学了什么”之前，先记录“这个知识点想解决什么问题”。")

    with st.form("add_study_session"):
        st.subheader("添加今日学习记录")
        cols = st.columns(3)
        session_date = cols[0].date_input("日期", value=date.today())
        subject = cols[1].text_input("科目", placeholder="例如：信号与系统")
        chapter = cols[2].text_input("章节 / PPT / 课程名称")
        title = st.text_input("今日学习主题", placeholder="例如：Z 反变换、系统稳定性、极零图")
        main_question = st.text_area("核心问题", placeholder="这个主题想解决什么问题？")
        mastered_content = st.text_area("已掌握内容")
        blockers = st.text_area("卡点")
        wrong_questions = st.text_area("错题或不会的问题")
        summary = st.text_area("主线讲解整理 / 总结")
        mastery = st.slider("掌握度", 0, 100, 60)
        cols = st.columns(3)
        need_review = cols[0].checkbox("需要复习", value=True)
        is_key = cols[1].checkbox("加入重点知识点", value=mastery < 70)
        create_card = cols[2].checkbox("同时创建知识点卡片")
        submitted = st.form_submit_button("保存学习记录")

    if submitted:
        if not subject.strip() or not title.strip() or not main_question.strip():
            st.error("科目、今日学习主题、核心问题不能为空。")
        else:
            session_id = insert_and_get_id(
                """
                INSERT INTO study_sessions (
                    user_id, date, subject, chapter, title, main_question, mastered_content,
                    blockers, wrong_questions, summary, mastery, need_review, is_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    session_date.isoformat(),
                    subject.strip(),
                    chapter.strip(),
                    title.strip(),
                    main_question.strip(),
                    mastered_content.strip(),
                    blockers.strip(),
                    wrong_questions.strip(),
                    summary.strip(),
                    mastery,
                    int(need_review),
                    int(is_key),
                ),
            )
            if create_card:
                knowledge_id = insert_and_get_id(
                    """
                    INSERT INTO knowledge_cards (
                        user_id, subject, topic, core_question, one_sentence, logic_or_formula,
                        application, mastery, need_review, source_session_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.id,
                        subject.strip(),
                        title.strip(),
                        main_question.strip(),
                        mastered_content.strip() or "待补充一句话解释",
                        summary.strip(),
                        wrong_questions.strip(),
                        mastery,
                        int(need_review),
                        session_id,
                    ),
                )
                if need_review:
                    create_initial_review_tasks(knowledge_id, session_date, user_id=user.id)
            st.success("学习记录已保存。")

    st.divider()
    st.subheader("历史学习记录")
    records = fetch_all("SELECT * FROM study_sessions WHERE user_id = ? ORDER BY date DESC, id DESC", (user.id,))
    if not records:
        st.info("暂无学习记录。")
        return

    subjects = sorted({item["subject"] for item in records})
    selected_subject = st.selectbox("按科目筛选", ["全部"] + subjects)
    filtered = records if selected_subject == "全部" else [r for r in records if r["subject"] == selected_subject]
    st.dataframe(
        pd.DataFrame(filtered)[["id", "date", "subject", "chapter", "title", "main_question", "mastery"]],
        use_container_width=True,
        hide_index=True,
    )

    selected_id = st.selectbox(
        "选择要编辑的记录",
        [r["id"] for r in filtered],
        format_func=lambda item_id: f"#{item_id} - {next(r['title'] for r in filtered if r['id'] == item_id)}",
    )
    record = fetch_one("SELECT * FROM study_sessions WHERE id = ? AND user_id = ?", (selected_id, user.id))
    if not record:
        return

    with st.form(f"edit_study_session_{selected_id}"):
        st.subheader("编辑学习记录")
        cols = st.columns(3)
        edit_date = cols[0].date_input("日期", value=_date_value(record["date"]), key=f"date_{selected_id}")
        edit_subject = cols[1].text_input("科目", value=record["subject"])
        edit_chapter = cols[2].text_input("章节 / PPT / 课程名称", value=record["chapter"] or "")
        edit_title = st.text_input("今日学习主题", value=record["title"])
        edit_question = st.text_area("核心问题", value=record["main_question"])
        edit_mastered = st.text_area("已掌握内容", value=record["mastered_content"] or "")
        edit_blockers = st.text_area("卡点", value=record["blockers"] or "")
        edit_wrong = st.text_area("错题或不会的问题", value=record["wrong_questions"] or "")
        edit_summary = st.text_area("主线讲解整理 / 总结", value=record["summary"] or "")
        edit_mastery = st.slider("掌握度", 0, 100, int(record["mastery"]), key=f"mastery_{selected_id}")
        cols = st.columns(2)
        edit_need_review = cols[0].checkbox("需要复习", value=bool(record["need_review"]))
        edit_is_key = cols[1].checkbox("加入重点知识点", value=bool(record["is_key"]))
        update_submitted = st.form_submit_button("更新记录")

    if update_submitted:
        execute(
            """
            UPDATE study_sessions
            SET date = ?, subject = ?, chapter = ?, title = ?, main_question = ?,
                mastered_content = ?, blockers = ?, wrong_questions = ?, summary = ?,
                mastery = ?, need_review = ?, is_key = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                edit_date.isoformat(),
                edit_subject.strip(),
                edit_chapter.strip(),
                edit_title.strip(),
                edit_question.strip(),
                edit_mastered.strip(),
                edit_blockers.strip(),
                edit_wrong.strip(),
                edit_summary.strip(),
                edit_mastery,
                int(edit_need_review),
                int(edit_is_key),
                selected_id,
                user.id,
            ),
        )
        st.success("学习记录已更新。")
        st.rerun()
