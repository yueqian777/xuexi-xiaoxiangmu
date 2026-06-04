from __future__ import annotations

import pandas as pd
import streamlit as st

from models import REVIEW_RESULTS
from services.auth_service import require_login
from services.review_service import get_all_pending_review_tasks, get_today_review_tasks, mark_review_result


def render() -> None:
    user = require_login()
    user_id = user.id
    st.title("复习计划")
    st.caption("复习结果会自动调整掌握度；仍然模糊和完全不会会追加复习任务。")

    today_tasks = get_today_review_tasks(user_id=user_id)
    all_pending = get_all_pending_review_tasks(user_id=user_id)

    st.subheader("今日复习")
    if today_tasks:
        st.dataframe(
            pd.DataFrame(today_tasks)[
                [
                    "id",
                    "review_date",
                    "review_stage",
                    "subject",
                    "topic",
                    "mastery",
                    "last_cause",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("今天没有到期复习任务。")

    st.subheader("标记复习结果")
    if all_pending:
        task_id = st.selectbox(
            "选择待复习任务",
            [task["id"] for task in all_pending],
            format_func=lambda item_id: _task_label(all_pending, item_id),
        )
        selected = next(task for task in all_pending if task["id"] == task_id)
        st.write(f"推荐自测问题：请闭卷解释「{selected['topic']}」的核心问题、关键逻辑和典型应用。")
        result = st.selectbox("复习结果", REVIEW_RESULTS)
        if st.button("保存复习结果"):
            mark_review_result(task_id, result)
            st.success("复习结果已保存，掌握度和后续复习已自动调整。")
            st.rerun()
    else:
        st.caption("暂无待复习任务。")

    st.subheader("全部待复习")
    if all_pending:
        st.dataframe(
            pd.DataFrame(all_pending)[
                ["id", "review_date", "review_stage", "subject", "topic", "mastery", "status"]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("暂无待复习任务。")


def _task_label(tasks: list[dict], task_id: int) -> str:
    task = next(item for item in tasks if item["id"] == task_id)
    return f"#{task_id} · {task['review_date']} · {task['subject']} · {task['topic']} · {task['review_stage']}"
