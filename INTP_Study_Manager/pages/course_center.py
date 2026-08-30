from __future__ import annotations

import json
from datetime import date
from typing import Any

import streamlit as st

from db import fetch_all, fetch_one
from services.active_learning_context_service import get_active_context
from services.auth_service import require_login
from services.course_service import (
    archive_course,
    complete_course,
    create_course,
    get_course_detail,
    list_courses,
    reactivate_course,
)
from services.ppt_reader_state import (
    parse_reader_position,
    reader_deck_position_setting_key,
    reader_position_setting_key,
)
from services.ui_helpers import render_workbench_header, set_navigation_target


STATUS_LABELS = {
    "active": "学习中",
    "completed": "已完成",
    "archived": "已归档",
}
OUTCOME_LABELS = {
    "completed": "已完成",
    "archived": "已归档",
}
PPT_PENDING_LEARNING_TARGET_KEY = "ppt_pending_learning_target"
COURSE_REPORT_STATE_KEY = "course_center_report_course_id"


def render() -> None:
    user = require_login()
    user_id = user.id
    report_course_id = _positive_session_int(st.session_state.get(COURSE_REPORT_STATE_KEY))
    if report_course_id:
        detail = get_course_detail(user_id, report_course_id)
        if detail:
            _render_course_report(detail)
            return
        st.session_state.pop(COURSE_REPORT_STATE_KEY, None)

    render_workbench_header(
        "课程中心",
        "从课程卡片继续学习、查看报告或开启新的复习周期；历史数据始终保留。",
    )

    _render_create_course(user_id)
    courses = list_courses(user_id)
    active = [item for item in courses if item["status"] == "active"]
    history = [item for item in courses if item["status"] != "active"]
    active_context = get_active_context(user_id)

    st.subheader("当前学习")
    if active:
        _render_course_grid(user_id, active, active_context=active_context)
    else:
        st.info("当前没有正在学习的课程。可以新建课程，或从历史课程重新激活。")

    st.subheader("历史课程")
    if history:
        _render_course_grid(user_id, history, active_context=active_context)
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


def _render_course_grid(
    user_id: int,
    courses: list[dict],
    *,
    active_context: dict,
) -> None:
    for start in range(0, len(courses), 2):
        columns = st.columns(2)
        for offset, course in enumerate(courses[start : start + 2]):
            with columns[offset]:
                _render_course_card(
                    user_id,
                    course,
                    active_context=active_context,
                )


def _render_course_card(
    user_id: int,
    course: dict,
    *,
    active_context: dict,
) -> None:
    course_id = int(course["id"])
    detail = get_course_detail(user_id, course_id)
    if not detail:
        return
    model = _course_card_view_model(course, detail, active_context)
    decks = detail.get("decks") or []
    phases = detail.get("learning_phases") or []
    persisted_position = (
        _course_persisted_learning_target(user_id, decks)
        if course.get("status") == "active"
        else None
    )
    model = _course_card_view_model(
        course,
        detail,
        active_context,
        persisted_position=persisted_position,
    )

    with st.container(border=True):
        heading, status = st.columns([2.2, 1])
        heading.markdown(f"### {model['name']}")
        status.markdown(f"**{model['status_label']}**")
        cycle_prefix = "当前阶段" if course["status"] == "active" else "最近周期"
        st.caption(
            f"{cycle_prefix}：{model['cycle_label']} · {len(phases)} 个学习周期 · "
            f"完成时间：{model['completed_at']}"
        )

        st.markdown("**学习进度**")
        progress_percent = model.get("progress_percent")
        if progress_percent is None:
            st.caption(model["progress_label"])
        else:
            st.progress(
                int(progress_percent),
                text=model["progress_label"],
            )

        first_metrics = st.columns(2)
        first_metrics[0].metric("PPT 数量", model["ppt_count"])
        first_metrics[1].metric("问题数量", model["question_count"])
        second_metrics = st.columns(2)
        second_metrics[0].metric("知识卡数量", model["knowledge_count"])
        second_metrics[1].metric(
            "掌握度",
            f"{model['mastery']}%" if model["mastery"] is not None else "—",
        )

        primary_actions = st.columns(2)
        if decks:
            open_label = "继续学习" if course["status"] == "active" else "查看历史"
            if primary_actions[0].button(
                open_label,
                key=f"course_open_{course_id}",
                use_container_width=True,
                type="primary" if course["status"] == "active" else "secondary",
            ):
                _open_course_deck(user_id, course, decks)
        else:
            primary_actions[0].caption("尚未添加 PPT / PDF")

        if primary_actions[1].button(
            "查看总结",
            key=f"course_report_{course_id}",
            use_container_width=True,
        ):
            st.session_state[COURSE_REPORT_STATE_KEY] = course_id
            st.rerun()

        if course["status"] == "active":
            lifecycle_actions = st.columns(2)
            with lifecycle_actions[0].popover("结束课程", use_container_width=True):
                st.caption("选择完成课程后，会冻结本学习周期的课程学习报告。")
                if st.button(
                    "确认完成",
                    type="primary",
                    key=f"course_complete_{course_id}",
                    use_container_width=True,
                ):
                    complete_course(user_id, course_id)
                    st.session_state[COURSE_REPORT_STATE_KEY] = course_id
                    st.rerun()
            if lifecycle_actions[1].button(
                "归档",
                key=f"course_archive_{course_id}",
                use_container_width=True,
            ):
                archive_course(user_id, course_id)
                st.success("课程已归档，所有学习数据均已保留。")
                st.rerun()
        else:
            lifecycle_actions = st.columns(2)
            _render_reactivation(
                lifecycle_actions[0],
                user_id,
                course,
                phases,
            )
            if course["status"] == "completed":
                if lifecycle_actions[1].button(
                    "归档",
                    key=f"course_archive_{course_id}",
                    use_container_width=True,
                ):
                    archive_course(user_id, course_id)
                    st.success("课程已归档。")
                    st.rerun()


def _render_reactivation(
    host: Any,
    user_id: int,
    course: dict,
    phases: list[dict],
) -> None:
    course_id = int(course["id"])
    next_cycle = _next_learning_cycle_view_model(phases)
    with host.popover("重新激活", use_container_width=True):
        st.markdown(
            f"**将创建：{next_cycle['phase_heading']} · {next_cycle['label']}**"
        )
        st.caption("历史周期不会被覆盖；本次学习会作为新的周期继续记录。")
        if st.button(
            "开始新周期",
            type="primary",
            key=f"course_reactivate_{course_id}",
            use_container_width=True,
        ):
            try:
                reactivated = reactivate_course(user_id, course_id)
            except ValueError as exc:
                st.error(str(exc))
                return
            if reactivated:
                st.success(
                    f"已开始「{next_cycle['label']}」；历史阶段与报告保持不变。"
                )
            st.rerun()


def _render_course_report(detail: dict) -> None:
    course = detail["course"]
    report = _course_report_view_model(detail)
    render_workbench_header(
        "课程学习报告",
        "完成课程后冻结报告；重新激活只会新增学习周期，不覆盖旧记录。",
    )
    if st.button("← 返回课程中心", key="course_report_back"):
        st.session_state.pop(COURSE_REPORT_STATE_KEY, None)
        st.rerun()

    heading, status = st.columns([3, 1])
    heading.title(str(course.get("name") or "未命名课程"))
    status.metric("状态", STATUS_LABELS.get(course.get("status"), course.get("status")))
    if detail.get("summary") is None:
        st.info("当前展示学习进展预览；完成课程后，本周期报告会被冻结保存。")
    elif course.get("status") == "active":
        st.info("这是上一学习周期总结；当前周期完成后会生成新的报告快照。")

    overview = st.columns(4)
    overview[0].metric("学习时间", report["learning_time"])
    overview[1].metric("完成内容", report["completed_content"])
    resolved_count = report["resolved_question_count"]
    resolved_label = "历史版本未记录" if resolved_count is None else str(resolved_count)
    overview[2].metric(
        "解决问题数量",
        f"{resolved_label} / {report['question_count']}",
    )
    overview[3].metric("知识卡数量", report["knowledge_count"])

    mastery = report.get("mastery")
    st.metric("综合掌握度", f"{mastery}%" if mastery is not None else "尚无知识卡")

    st.subheader("完成内容")
    st.markdown(f"**{report['completed_content']}**")
    decks = _report_deck_rows(detail)
    if detail.get("summary") is not None:
        st.caption("本周期仅展示冻结的资料与页数总计；后续重新关联不会改写历史报告。")
    elif decks:
        for deck in decks:
            st.markdown(
                f"- {deck.get('title') or deck.get('filename') or '未命名资料'}"
                f" · {int(deck.get('slide_count') or 0)} 页"
            )
    else:
        st.caption("本课程尚未关联 PPT / PDF。")

    knowledge_columns = st.columns(2)
    with knowledge_columns[0]:
        st.subheader("知识体系")
        _render_knowledge_list(report["core_knowledge"], empty="暂无已掌握知识卡")
    with knowledge_columns[1]:
        st.subheader("薄弱点")
        _render_knowledge_list(report["weak_points"], empty="暂无明显薄弱点")

    st.subheader("未来复习建议")
    st.info(report["future_review_advice"])

    st.subheader("学习周期")
    st.caption("每次重新激活都会新增周期；历史周期不会被覆盖。")
    _render_learning_cycles(detail.get("learning_phases") or [])


def _render_knowledge_list(items: list[dict], *, empty: str) -> None:
    if not items:
        st.caption(empty)
        return
    for item in items:
        topic = item.get("topic") if isinstance(item, dict) else item
        mastery = item.get("mastery") if isinstance(item, dict) else None
        suffix = f" · 掌握度 {int(mastery)}%" if mastery is not None else ""
        st.markdown(f"- {topic or '未命名知识点'}{suffix}")


def _render_learning_cycles(phases: list[dict]) -> None:
    models = _learning_cycle_view_models(phases)
    if not models:
        st.caption("还没有学习周期记录。")
        return
    for start in range(0, len(models), 3):
        columns = st.columns(3)
        for offset, model in enumerate(models[start : start + 3]):
            with columns[offset]:
                with st.container(border=True):
                    st.markdown(f"**{model['phase_heading']}**")
                    st.markdown(f"### {model['label']}")
                    if model["is_current"]:
                        st.success("当前阶段")
                    else:
                        st.caption(model["outcome_label"])
                    st.caption(model["period_label"])
                    if model["has_snapshot"]:
                        st.caption("本周期报告快照已保留")
                        with st.expander("查看本周期报告", expanded=False):
                            st.markdown(
                                _summary_fallback(
                                    model["snapshot"],
                                    historical_snapshot=True,
                                )
                            )


def _course_card_view_model(
    course: dict,
    detail: dict,
    active_context: dict,
    *,
    persisted_position: dict[str, int] | None = None,
) -> dict[str, Any]:
    decks = detail.get("decks") or []
    phases = detail.get("learning_phases") or []
    metrics = detail.get("metrics") or detail.get("summary") or {}
    mastery = _average_mastery(metrics)
    progress_label, progress_percent = _course_progress(
        course,
        decks,
        phases,
        active_context,
        persisted_position=persisted_position,
    )
    current_cycle = _learning_cycle_view_models(phases)
    stored_summary = detail.get("summary")
    ppt_count = (
        int(stored_summary.get("deck_count") or 0)
        if course.get("status") != "active" and stored_summary is not None
        else len(decks)
    )
    return {
        "name": str(course.get("name") or "未命名课程"),
        "status_label": STATUS_LABELS.get(course.get("status"), course.get("status")),
        "completed_at": _completion_date(course, phases),
        "progress_label": progress_label,
        "progress_percent": progress_percent,
        "ppt_count": ppt_count,
        "question_count": int(metrics.get("question_count") or 0),
        "knowledge_count": int(metrics.get("knowledge_count") or 0),
        "mastery": mastery,
        "cycle_label": current_cycle[-1]["label"] if current_cycle else "尚未开始学习周期",
    }


def _report_deck_rows(detail: dict) -> list[dict]:
    if detail.get("summary") is not None:
        return []
    return list(detail.get("decks") or [])


def _course_report_view_model(detail: dict) -> dict[str, Any]:
    stored_summary = detail.get("summary")
    frozen = stored_summary or detail.get("metrics") or {}
    live = detail.get("metrics") or frozen
    started_at = _date_label(frozen.get("started_at")) or "未记录"
    ended_at = _date_label(
        frozen.get("completed_at")
        or frozen.get("archived_at")
        or frozen.get("last_activity_at")
    ) or "进行中"
    frozen_resolved = frozen.get("resolved_question_count")
    if frozen_resolved is not None:
        resolved_question_count: int | None = int(frozen_resolved)
    elif stored_summary is not None:
        resolved_question_count = None
    else:
        resolved_question_count = int(live.get("resolved_question_count") or 0)
    return {
        "learning_time": f"{started_at} 至 {ended_at}",
        "completed_content": (
            f"{int(frozen.get('deck_count') or 0)} 份资料 · "
            f"{int(frozen.get('slide_count') or 0)} 页"
        ),
        "resolved_question_count": resolved_question_count,
        "question_count": int(frozen.get("question_count") or 0),
        "knowledge_count": int(frozen.get("knowledge_count") or 0),
        "mastery": _average_mastery(frozen),
        "core_knowledge": frozen.get("core_knowledge") or [],
        "weak_points": frozen.get("weak_points") or frozen.get("weak_knowledge") or [],
        "future_review_advice": str(
            frozen.get("future_review_advice")
            or frozen.get("future_review_suggestion")
            or "继续按 1-3-7-14 节奏复习，并优先处理低掌握度知识点。"
        ),
    }


def _course_progress(
    course: dict,
    decks: list[dict],
    phases: list[dict],
    active_context: dict,
    *,
    persisted_position: dict[str, int] | None = None,
) -> tuple[str, int | None]:
    status = str(course.get("status") or "")
    latest_phase = max(
        phases,
        key=lambda phase: int(phase.get("phase_number") or 0),
        default={},
    )
    latest_outcome = str(latest_phase.get("outcome") or "")
    if status == "completed" or (status == "archived" and latest_outcome == "completed"):
        return "课程已完成", 100
    if status == "archived":
        return "课程已归档", None

    position = persisted_position or active_context
    position_is_active = persisted_position is not None or position.get("active")
    context_deck_id = int(position.get("deck_id") or 0) if position_is_active else 0
    deck = next(
        (item for item in decks if int(item.get("id") or 0) == context_deck_id),
        None,
    )
    if not deck:
        return "尚未开始阅读", 0
    total = max(1, int(deck.get("slide_count") or 1))
    current = min(total, max(1, int(position.get("slide_number") or 1)))
    title = str(deck.get("title") or deck.get("filename") or "未命名资料")
    return (
        f"当前《{title}》第 {current} / {total} 页",
        None,
    )


def _average_mastery(summary: dict) -> int | None:
    cards: list[dict] = []
    seen: set[object] = set()
    for key in ("core_knowledge", "weak_points", "weak_knowledge"):
        for item in summary.get(key) or []:
            if not isinstance(item, dict) or item.get("mastery") is None:
                continue
            identity: object = item.get("knowledge_id") or (
                str(item.get("topic") or ""),
                int(item.get("mastery") or 0),
            )
            if identity in seen:
                continue
            seen.add(identity)
            cards.append(item)
    if not cards:
        return None
    return round(sum(int(item.get("mastery") or 0) for item in cards) / len(cards))


def _learning_cycle_view_models(phases: list[dict]) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for phase in phases:
        number = max(1, int(phase.get("phase_number") or len(models) + 1))
        started_at = str(phase.get("started_at") or phase.get("created_at") or "")
        ended_at = str(phase.get("ended_at") or "")
        outcome = str(phase.get("outcome") or "")
        snapshot = _phase_summary_snapshot(phase.get("course_summary"))
        models.append(
            {
                "phase_heading": f"阶段 {number}",
                "label": _learning_cycle_label(number, started_at),
                "is_current": not ended_at,
                "outcome_label": OUTCOME_LABELS.get(outcome, outcome or "已结束"),
                "period_label": (
                    f"{_date_label(started_at) or '未记录'} 至 "
                    f"{_date_label(ended_at) or '现在'}"
                ),
                "has_snapshot": snapshot is not None,
                "snapshot": snapshot,
            }
        )
    return models


def _next_learning_cycle_view_model(
    phases: list[dict],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    current_date = today or date.today()
    number = max(
        [int(phase.get("phase_number") or 0) for phase in phases] or [0]
    ) + 1
    started_at = current_date.isoformat()
    return {
        "phase_heading": f"阶段 {number}",
        "label": _learning_cycle_label(number, started_at),
    }


def _learning_cycle_label(phase_number: int, started_at: str) -> str:
    date_text = _date_label(started_at)
    try:
        year = int(date_text[:4])
        month = int(date_text[5:7])
    except (TypeError, ValueError):
        return f"第 {max(1, int(phase_number))} 学习周期"
    if int(phase_number) <= 1:
        semester = "春季" if 1 <= month <= 6 else "秋季"
        return f"{year}{semester}学习"
    return f"{year}复习阶段"


def _completion_date(course: dict, phases: list[dict]) -> str:
    direct = _date_label(course.get("completed_at"))
    if direct:
        return direct
    completed_phases = [
        phase
        for phase in phases
        if str(phase.get("outcome") or "") == "completed" and phase.get("ended_at")
    ]
    if completed_phases:
        return _date_label(completed_phases[-1].get("ended_at")) or "—"
    return "—"


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
    persisted = _course_persisted_learning_target(user_id, decks)
    if persisted:
        return persisted
    context = get_active_context(user_id)
    deck_ids = {int(deck["id"]) for deck in decks}
    context_deck_id = int(context.get("deck_id") or 0) if context.get("active") else 0
    if context_deck_id in deck_ids:
        return {
            "deck_id": context_deck_id,
            "slide_number": max(1, int(context.get("slide_number") or 1)),
        }
    return {"deck_id": int(decks[0]["id"]), "slide_number": 1}


def _course_persisted_learning_target(
    user_id: int,
    decks: list[dict],
) -> dict[str, int] | None:
    deck_by_id = {int(deck["id"]): deck for deck in decks}
    if not deck_by_id:
        return None

    keys = [
        reader_deck_position_setting_key(user_id, deck_id)
        for deck_id in deck_by_id
    ]
    placeholders = ", ".join("?" for _ in keys)
    rows = fetch_all(
        f"""
        SELECT key, value, updated_at
        FROM app_settings
        WHERE user_id = ? AND key IN ({placeholders})
        ORDER BY updated_at DESC, key ASC
        """,
        (int(user_id), *keys),
    )
    candidates: list[tuple[dict[str, int], int]] = []
    for row in rows:
        position = parse_reader_position(row.get("value"))
        target = _course_position_for_decks(position, deck_by_id)
        if target:
            candidates.append((target, int(position.get("saved_at_ns") or 0)))
    if candidates:
        timestamped = [candidate for candidate in candidates if candidate[1] > 0]
        if timestamped:
            return max(timestamped, key=lambda candidate: candidate[1])[0]
        return candidates[0][0]

    global_row = fetch_one(
        "SELECT value FROM app_settings WHERE key = ? AND user_id = ?",
        (reader_position_setting_key(user_id), int(user_id)),
    )
    global_position = parse_reader_position(global_row.get("value")) if global_row else {}
    return _course_position_for_decks(global_position, deck_by_id)


def _course_position_for_decks(
    position: dict[str, int],
    deck_by_id: dict[int, dict],
) -> dict[str, int] | None:
    deck_id = int(position.get("deck_id") or 0)
    if deck_id not in deck_by_id:
        return None
    slide_number = max(1, int(position.get("slide_number") or 1))
    slide_count = int(deck_by_id[deck_id].get("slide_count") or 0)
    if slide_count > 0:
        slide_number = min(slide_number, slide_count)
    return {"deck_id": deck_id, "slide_number": slide_number}


def _summary_fallback(
    summary: dict,
    *,
    historical_snapshot: bool = False,
) -> str:
    detail = {"summary": summary, "metrics": summary}
    if historical_snapshot:
        detail["course"] = {"status": "active"}
    report = _course_report_view_model(detail)
    resolved_label = (
        "历史版本未记录"
        if report["resolved_question_count"] is None
        else str(report["resolved_question_count"])
    )
    core_labels = [
        str(item.get("topic") or "未命名知识点") if isinstance(item, dict) else str(item)
        for item in report["core_knowledge"]
    ]
    weak_labels = [
        str(item.get("topic") or "未命名知识点") if isinstance(item, dict) else str(item)
        for item in report["weak_points"]
    ]
    return "\n\n".join(
        [
            f"**学习时间**：{report['learning_time']}",
            f"**完成内容**：{report['completed_content']}",
            f"**解决问题数量**：{resolved_label} / {report['question_count']}",
            f"**知识卡数量**：{report['knowledge_count']}",
            f"**核心知识体系**：{'、'.join(core_labels) if core_labels else '暂无'}",
            f"**薄弱点**：{'、'.join(weak_labels) if weak_labels else '暂无'}",
            f"**未来复习建议**：{report['future_review_advice']}",
        ]
    )


def _date_label(value: object) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def _phase_summary_snapshot(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value or None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload else None


def _positive_session_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
