from __future__ import annotations

import streamlit as st

from services.auth_service import require_login
from services.active_learning_context_service import get_active_context
from services.course_service import (
    archive_course,
    complete_course,
    create_course,
    get_course_detail,
    list_courses,
    reactivate_course,
)
from services.ui_helpers import render_workbench_header, set_navigation_target


STATUS_LABELS = {
    "active": "学习中",
    "completed": "已完成",
    "archived": "已归档",
}
PPT_PENDING_LEARNING_TARGET_KEY = "ppt_pending_learning_target"


def render() -> None:
    user = require_login()
    user_id = user.id
    render_workbench_header(
        "课程中心",
        "课程结束只改变生命周期，不会删除 PPT、插问、知识卡或复习记录。",
    )

    _render_create_course(user_id)
    courses = list_courses(user_id)
    active = [item for item in courses if item["status"] == "active"]
    history = [item for item in courses if item["status"] != "active"]

    st.subheader("当前学习")
    if active:
        for course in active:
            _render_course_card(user_id, course, historical=False)
    else:
        st.info("当前没有正在学习的课程。可以新建课程，或从历史课程重新激活。")

    st.subheader("历史课程")
    if history:
        for course in history:
            _render_course_card(user_id, course, historical=True)
    else:
        st.caption("还没有已完成或已归档课程。")


def _render_create_course(user_id: int) -> None:
    with st.expander("新建课程", expanded=False):
        with st.form("create_course_form", clear_on_submit=True):
            name = st.text_input("课程名称", placeholder="例如：信号与系统")
            submitted = st.form_submit_button("创建并开始学习", type="primary")
        if not submitted:
            return
        try:
            course = create_course(user_id, name)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.success(f"已创建课程「{course['name']}」，状态为学习中。")
        st.rerun()


def _render_course_card(user_id: int, course: dict, *, historical: bool) -> None:
    course_id = int(course["id"])
    detail = get_course_detail(user_id, course_id)
    if not detail:
        return
    decks = detail.get("decks") or []
    summary = detail.get("summary")
    phases = detail.get("learning_phases") or []

    with st.container(border=True):
        title_col, status_col, stats_col = st.columns([2.2, 1, 1.6])
        title_col.markdown(f"### {course['name']}")
        status_col.markdown(f"**状态：{STATUS_LABELS.get(course['status'], course['status'])}**")
        stats_col.caption(f"资料 {len(decks)} 份 · 学习阶段 {len(phases)} 个")

        action_cols = st.columns(4)
        if decks:
            label = "继续学习" if not historical else "进入历史课程"
            if action_cols[0].button(
                label,
                key=f"course_open_{course_id}",
                use_container_width=True,
            ):
                _open_course_deck(user_id, course, decks)
        else:
            action_cols[0].caption("尚未添加 PPT / PDF")

        if course["status"] == "active":
            with action_cols[1].popover("结束课程", use_container_width=True):
                outcome = st.radio(
                    "请选择",
                    ["已完成本课程学习", "暂停学习并归档"],
                    key=f"course_end_outcome_{course_id}",
                )
                st.caption("为保护学习历史，不提供删除课程数据。")
                if st.button(
                    "确认结束课程",
                    type="primary",
                    key=f"course_end_confirm_{course_id}",
                ):
                    if outcome == "已完成本课程学习":
                        complete_course(user_id, course_id)
                        st.success("课程已完成，并已生成课程学习总结。")
                    else:
                        archive_course(user_id, course_id)
                        st.success("课程已归档，所有学习数据均已保留。")
                    st.rerun()
        elif course["status"] == "completed":
            if action_cols[1].button(
                "归档",
                key=f"course_archive_{course_id}",
                use_container_width=True,
            ):
                archive_course(user_id, course_id)
                st.success("课程已归档。")
                st.rerun()

        if course["status"] != "active":
            if action_cols[2].button(
                "重新激活",
                key=f"course_reactivate_{course_id}",
                use_container_width=True,
            ):
                reactivate_course(user_id, course_id)
                st.success("课程已重新激活，并创建了新的学习阶段；历史阶段未被覆盖。")
                st.rerun()

        with st.expander("查看总结", expanded=False):
            if summary:
                st.markdown(summary.get("summary_markdown") or _summary_fallback(summary))
            elif course["status"] == "active":
                st.caption("完成课程时会自动生成学习日期范围、资料页数、插问、知识卡与复习建议。")
            else:
                st.caption("当前课程还没有可用总结。")


def _open_course_deck(user_id: int, course: dict, decks: list[dict]) -> None:
    target = _course_learning_target(user_id, decks)
    st.session_state[PPT_PENDING_LEARNING_TARGET_KEY] = {
        **target,
        "course_id": int(course["id"]),
        "include_history": course.get("status") != "active",
    }
    set_navigation_target("materials", "ppt_tutor")
    st.rerun()


def _course_learning_target(user_id: int, decks: list[dict]) -> dict[str, int]:
    if not decks:
        raise ValueError("课程没有可进入的学习资料。")
    context = get_active_context(user_id)
    deck_ids = {int(deck["id"]) for deck in decks}
    context_deck_id = int(context.get("deck_id") or 0) if context.get("active") else 0
    if context_deck_id in deck_ids:
        return {
            "deck_id": context_deck_id,
            "slide_number": max(1, int(context.get("slide_number") or 1)),
        }
    return {"deck_id": int(decks[0]["id"]), "slide_number": 1}


def _summary_fallback(summary: dict) -> str:
    core_knowledge = summary.get("core_knowledge") or []
    core_labels = [
        str(item.get("topic") or "未命名知识点") if isinstance(item, dict) else str(item)
        for item in core_knowledge
    ]
    weak_points = summary.get("weak_points") or []
    weak_labels = [
        str(item.get("topic") or "未命名知识点") if isinstance(item, dict) else str(item)
        for item in weak_points
    ]
    started_at = _date_label(summary.get("started_at")) or "未记录"
    ended_at = _date_label(summary.get("completed_at") or summary.get("archived_at")) or "进行中"
    return "\n\n".join(
        [
            f"**课程基本信息**：{summary.get('name') or '未命名课程'}",
            f"**学习时间**：{started_at} 至 {ended_at}",
            f"**资料与页面**：{summary.get('deck_count', 0)} 份资料，{summary.get('slide_count', 0)} 页",
            f"**学习沉淀**：{summary.get('study_session_count', 0)} 次学习记录，{summary.get('question_count', 0)} 个插问，{summary.get('knowledge_count', 0)} 张知识卡",
            f"**复习完成**：{summary.get('completed_review_count', 0)} / {summary.get('review_count', 0)}",
            f"**核心知识体系**：{'、'.join(core_labels) if core_labels else '暂无已掌握知识卡'}",
            f"**未完全掌握**：{'、'.join(weak_labels) if weak_labels else '暂无'}",
            f"**未来复习建议**：{summary.get('future_review_advice') or '继续按 1-3-7-14 节奏复习。'}",
        ]
    )


def _date_label(value: object) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text
