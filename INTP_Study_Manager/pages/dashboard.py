from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from services.review_service import get_today_review_tasks
from services.reminder_service import get_daily_reminder_config, get_today_review_log, is_daily_review_due_now
from services.stats_service import low_mastery_cards, open_parking_questions, recent_blockers


def _self_test_question(topic: str) -> str:
    return f"请闭卷解释「{topic}」解决什么核心问题，并写出一句话解释、关键逻辑和一个典型应用。"


def render() -> None:
    st.title("首页 Dashboard")
    st.caption("每天先看复习，再登记新学习，最后生成闭卷回忆 Prompt。")

    today_tasks = get_today_review_tasks()
    low_cards = low_mastery_cards()
    blockers = recent_blockers()
    parking = open_parking_questions()
    reminder_config = get_daily_reminder_config()
    review_log = get_today_review_log()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("今日待复习", len(today_tasks))
    col2.metric("低于 70% 知识点", len(low_cards))
    col3.metric("最近卡点", len(blockers))
    col4.metric("停车场未解决", len(parking))

    with st.container(border=True):
        st.subheader("每日复盘提醒")
        if review_log:
            st.success(f"今日复盘已完成：{review_log['created_at']}")
        elif is_daily_review_due_now(reminder_config):
            st.warning("已经到每日复盘时间。请进入“每日复盘提醒”页面完成今日复盘。")
        elif reminder_config["enabled"]:
            st.info(f"今日 {reminder_config['time']} 会提醒你进行每日复盘。")
        else:
            st.caption("每日复盘提醒当前未启用。")

    st.subheader(f"今天需要复习什么：{date.today().isoformat()}")
    if today_tasks:
        for task in today_tasks:
            with st.container(border=True):
                cols = st.columns([1.2, 1.5, 1.2, 1.2, 2.2])
                cols[0].markdown(f"**{task['subject']}**")
                cols[1].markdown(task["topic"])
                cols[2].markdown(task["review_stage"])
                cols[3].markdown(f"掌握度：{task['mastery']}%")
                cols[4].markdown(_self_test_question(task["topic"]))
                if task.get("last_cause"):
                    st.caption(f"上次错因：{task['last_cause']}")
    else:
        st.info("今天没有到期复习任务。可以新增知识点卡片，系统会自动生成 1-3-7-14 复习。")

    st.subheader("今日学习记录入口")
    st.write("从左侧进入 **学习登记**，按“核心问题 + 已掌握内容 + 卡点 + 掌握度”记录今天的学习。")

    left, right = st.columns(2)
    with left:
        st.subheader("最近卡点")
        if blockers:
            st.dataframe(
                pd.DataFrame(blockers)[["date", "subject", "title", "blockers", "mastery"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("暂无卡点记录。")

    with right:
        st.subheader("掌握度低于 70% 的知识点")
        if low_cards:
            st.dataframe(
                pd.DataFrame(low_cards)[["subject", "topic", "mastery", "core_question"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("暂无低掌握度知识点。")

    st.subheader("探索停车场问题")
    if parking:
        st.dataframe(
            pd.DataFrame(parking)[["subject", "question", "source", "status", "created_at"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("暂无未解决的扩展问题。")
