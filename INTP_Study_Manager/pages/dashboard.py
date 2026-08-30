from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db import fetch_all, fetch_one
from services.active_learning_context_service import get_active_context
from services.ai_service import AIServiceError, DEFAULT_MODEL, list_api_providers, provider_label
from services.api_key_ui import render_local_secret_unlock
from services.api_runtime import (
    ensure_active_provider,
    ensure_provider_model,
    provider_model_state_key,
    save_default_api_config,
    set_active_provider,
)
from services.auth_service import require_login
from services.course_service import get_dashboard_snapshot
from services.daily_ai_review_service import (
    answers_payload,
    collect_review_candidates,
    daily_review_question_markdown,
    evaluate_today_ai_review,
    evaluation_payload,
    generate_today_ai_review_plan,
    get_today_ai_review_plan,
    plan_payload,
    regenerate_today_ai_review_plan,
)
from services.review_service import get_today_review_tasks
from services.reminder_service import get_daily_reminder_config, get_today_review_log, is_daily_review_due_now
from services.stats_service import low_mastery_cards, open_parking_questions, recent_blockers, recent_knowledge_links
from services.ui_helpers import render_workbench_header, set_navigation_target


def _go_to_page(label: str, *, section_id: str, page_id: str, key: str) -> None:
    if st.button(label, use_container_width=True, key=key):
        set_navigation_target(section_id, page_id)
        st.rerun()


def _self_test_question(topic: str) -> str:
    return f"请闭卷解释「{topic}」解决什么核心问题，并写出一句话解释、关键逻辑和一个典型应用。"


def _render_default_api_and_daily_ai_review() -> None:
    user = require_login()
    user_id = user.id
    _install_daily_review_styles()
    st.subheader("每日 AI 轻量复习")
    st.caption("少量闭卷检索题检查今天最值得复习的知识点；提交后自动批改，并写回知识点掌握度。")

    providers = list_api_providers(enabled_only=True, user_id=user_id)
    if not providers:
        st.warning("没有启用的 API Provider。请先进入“API 接入设置”创建或启用一个 Provider。")
        return

    provider_key, _ = ensure_active_provider(providers)
    provider_keys = [str(provider["provider_key"]) for provider in providers]
    provider_by_key = {str(provider["provider_key"]): provider for provider in providers}
    selected_index = provider_keys.index(str(provider_key)) if provider_key in provider_keys else 0

    with st.container(border=True):
        cols = st.columns([1.4, 1, 1])
        selected_provider_key = cols[0].selectbox(
            "项目默认 API",
            provider_keys,
            index=selected_index,
            format_func=lambda item_key: provider_label(provider_by_key[str(item_key)]),
            key="dashboard_default_api_provider",
        )
        provider = provider_by_key[str(selected_provider_key)]
        ensure_provider_model(provider)
        model = cols[1].text_input(
            "默认模型",
            key=provider_model_state_key(str(selected_provider_key)),
            help="后续页面没有主动切换 API 时，会沿用这个默认 Provider 和模型。",
        )
        max_tokens = cols[2].number_input(
            "复习输出 token",
            min_value=800,
            max_value=8000,
            value=int(st.session_state.get("daily_ai_review_max_tokens", 2200)),
            step=200,
        )
        st.session_state["daily_ai_review_max_tokens"] = int(max_tokens)

        active_model = model.strip() or provider.get("model") or DEFAULT_MODEL
        set_active_provider(str(selected_provider_key), active_model)
        key_name = f"api_key_provider_{selected_provider_key}"
        render_local_secret_unlock(
            provider,
            model=active_model,
            target_session_key=key_name,
            key_prefix=f"dashboard_default_provider_{selected_provider_key}",
            widget_session_key=f"dashboard_api_key_{selected_provider_key}",
        )
        api_key = st.text_input(
            "默认 API Key",
            value=st.session_state.get(key_name, ""),
            type="password",
            placeholder=f"不填则读取环境变量 {provider.get('api_key_env') or '未设置'}；也可以使用上方本地加密 Key 解锁。",
            key=f"dashboard_api_key_{selected_provider_key}",
        )
        st.session_state[key_name] = api_key

        cols = st.columns([1, 1, 2])
        if cols[0].button("保存为项目默认 API", type="primary"):
            save_default_api_config(str(selected_provider_key), active_model)
            st.success("项目默认 API 已保存。后续 API 任务未主动切换时会使用它。")
            st.rerun()

        candidates = collect_review_candidates(user_id=user_id)
        cols[1].metric("今日自测候选", len(candidates))
        if candidates:
            cols[2].caption("候选来自：今日到期复习、低于 70% 的知识点、仍需复习的知识卡片。")
        else:
            cols[2].caption("暂无候选知识点。先创建知识卡片或等待复习任务到期。")

    if not api_key and provider.get("auth_type") != "none" and not provider.get("api_key_env"):
        st.info("填写默认 API Key 后，首页会自动生成今天的轻量自测计划。")
        return

    plan = get_today_ai_review_plan(user_id=user_id)
    auto_key = f"daily_ai_review_auto_generated_{date.today().isoformat()}_{user_id}"
    if plan is None and candidates and not st.session_state.get(auto_key):
        st.session_state[auto_key] = True
        try:
            with st.spinner("正在自动生成今天的轻量复习提问..."):
                plan = generate_today_ai_review_plan(
                    provider_key=str(selected_provider_key),
                    api_key=api_key,
                    model=active_model,
                    max_output_tokens=int(max_tokens),
                    user_id=user_id,
                )
            st.success("今日轻量自测计划已生成。")
        except (AIServiceError, ValueError, RuntimeError) as exc:
            st.warning(f"今日自测计划暂未生成：{exc}")

    controls = st.columns([1, 1, 2])
    if controls[0].button("生成 / 重新生成今日自测", disabled=not bool(candidates)):
        try:
            with st.spinner("正在生成今日轻量复习提问..."):
                plan = regenerate_today_ai_review_plan(
                    provider_key=str(selected_provider_key),
                    api_key=api_key,
                    model=active_model,
                    max_output_tokens=int(max_tokens),
                    user_id=user_id,
                )
            st.success("今日自测计划已更新。")
            st.rerun()
        except (AIServiceError, ValueError, RuntimeError) as exc:
            st.error(f"生成失败：{exc}")
    controls[1].caption("建议每天 3-5 题；直接写中文、数字或选项，无需特殊公式格式。")

    plan = plan or get_today_ai_review_plan(user_id=user_id)
    if not plan:
        return

    _render_daily_ai_review_plan(
        plan,
        provider_key=str(selected_provider_key),
        api_key=api_key,
        model=active_model,
        max_tokens=int(max_tokens),
    )


def _render_daily_ai_review_plan(
    plan_row: dict,
    *,
    provider_key: str,
    api_key: str,
    model: str,
    max_tokens: int,
) -> None:
    plan = plan_payload(plan_row)
    evaluation = evaluation_payload(plan_row)
    saved_answers = answers_payload(plan_row)
    questions = plan.get("questions", [])

    with st.container(border=True):
        st.markdown(f"**今日复习主线：** {plan.get('main_line') or '少量问题检查今天最值得复习的知识点。'}")
        st.caption(f"状态：{plan_row.get('status')} · 生成时间：{plan_row.get('created_at')}")

        with st.form(f"daily_ai_review_answers_{plan_row['id']}"):
            answers: dict[str, str] = {}
            for index, question in enumerate(questions, start=1):
                question_id = str(question.get("question_id") or f"q{index}")
                st.markdown(daily_review_question_markdown(question, index))
                answers[question_id] = st.text_area(
                    "你的回答",
                    value=saved_answers.get(question_id, ""),
                    placeholder="直接写中文、数字、选项或一句理由；无需特殊公式格式。不会就写“不会”。",
                    key=f"daily_ai_answer_{plan_row['id']}_{question_id}",
                    height=110,
                )
            submitted = st.form_submit_button("提交回答并让 AI 批改")

        if submitted:
            try:
                with st.spinner("正在批改并更新掌握度..."):
                    evaluate_today_ai_review(
                        plan_row=plan_row,
                        answers=answers,
                        provider_key=provider_key,
                        api_key=api_key,
                        model=model,
                        max_output_tokens=max_tokens,
                    )
                st.success("批改完成，知识点掌握度已更新。")
                st.rerun()
            except (AIServiceError, ValueError, RuntimeError) as exc:
                st.error(f"批改失败：{exc}")

        if evaluation:
            _render_daily_ai_review_evaluation(evaluation)


def _render_daily_ai_review_evaluation(evaluation: dict) -> None:
    st.markdown("**AI 批改结果**")
    st.info(evaluation.get("overall_summary") or "已完成批改。")
    for item in evaluation.get("evaluations", []):
        with st.container(border=True):
            cols = st.columns([0.9, 0.9, 1.4])
            cols[0].metric("得分", f"{item.get('score', 0)}")
            cols[1].markdown(f"**{item.get('result')}**")
            cols[2].markdown(f"错因：**{item.get('cause_category')}**")
            st.progress(int(item.get("score") or 0), text="本题掌握度证据")
            if item.get("feedback"):
                st.markdown(f"**反馈**\n\n{item['feedback']}")
            if item.get("correct_answer"):
                st.markdown(f"**参考答案**\n\n{item['correct_answer']}")
            if item.get("next_question"):
                st.markdown(f"**下一轮最小追问**\n\n{item['next_question']}")

    updates = evaluation.get("mastery_updates") or []
    if updates:
        st.markdown("**掌握度更新**")
        for update in updates:
            before = int(update.get("mastery_before") or 0)
            after = int(update.get("mastery_after") or 0)
            delta = after - before
            with st.container(border=True):
                cols = st.columns([1.6, 0.8, 0.8, 0.8])
                cols[0].markdown(f"**{update.get('topic', '未命名知识点')}**")
                cols[1].metric("本次得分", int(update.get("score") or 0))
                cols[2].metric("掌握度", f"{after}%", delta=delta)
                cols[3].markdown(f"**{update.get('result')}**")


def _install_daily_review_styles() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stForm"] .stMarkdown h3 {
            margin-top: 0.35rem;
            margin-bottom: 0.2rem;
        }
        div[data-testid="stForm"] textarea {
            min-height: 96px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render() -> None:
    user = require_login()
    render_workbench_header(
        "今日学习驾驶舱",
        "先续上上次进度，再处理今天到期的复习与仍未解决的问题。",
    )

    snapshot = get_dashboard_snapshot(user.id)
    current_course = snapshot.get("current_course")
    active_courses = snapshot.get("active_courses") or []
    status_counts = snapshot.get("status_counts") or {}
    current_location = _current_learning_location(user.id, current_course)
    today_tasks = get_today_review_tasks(user_id=user.id, include_archived=False)

    st.subheader("今日学习")
    with st.container(border=True):
        if current_course:
            st.markdown(f"### 当前课程：{current_course['name']}")
            if current_location:
                location_parts = [
                    current_location.get("section_title"),
                    current_location.get("deck_title"),
                ]
                st.caption(" · ".join(str(item) for item in location_parts if item))
                if current_location.get("has_saved_position"):
                    st.markdown(
                        f"**继续：第 {current_location['slide_number']} 页**"
                        f" / 共 {current_location['slide_count']} 页"
                    )
                else:
                    st.markdown(
                        f"**从第 1 页开始** / 共 {current_location['slide_count']} 页"
                    )
                if st.button(
                    "继续学习",
                    type="primary",
                    key="dashboard_continue_learning",
                ):
                    st.session_state["ppt_pending_learning_target"] = {
                        "deck_id": current_location["deck_id"],
                        "slide_number": current_location["slide_number"],
                        "include_history": False,
                    }
                    set_navigation_target("materials", "ppt_tutor")
                    st.rerun()
            else:
                st.caption("这门课程还没有 PPT / PDF。进入 PPT 学习工作台添加第一份资料。")
                _go_to_page(
                    "添加学习资料",
                    section_id="materials",
                    page_id="ppt_tutor",
                    key="dashboard_add_material",
                )
        else:
            st.info("当前没有正在学习的课程。重新激活历史课程或创建一门新课程后，这里会恢复继续学习位置。")
            _go_to_page(
                "打开课程中心",
                section_id="today",
                page_id="course_center",
                key="dashboard_open_course_center",
            )

    st.subheader("今日复习与待解决")
    st.caption("今日任务只保留两条主线：复习到期知识点，解决当前课程插问。")
    unresolved_questions = _unresolved_question_count(user.id, current_course)
    unresolved_previews = _unresolved_question_previews(user.id, current_course)
    review_knowledge_count = _today_review_knowledge_count(today_tasks)
    task_cols = st.columns(2)
    with task_cols[0]:
        with st.container(border=True):
            st.metric(
                "今日复习",
                f"{review_knowledge_count} 个知识点",
                help="同一知识点的多个逾期阶段只计一次。",
            )
            for topic in _today_review_topics(today_tasks):
                st.caption(f"· {topic}")
            _go_to_page(
                "处理复习任务",
                section_id="review",
                page_id="reviews",
                key="dashboard_go_reviews",
            )
    with task_cols[1]:
        with st.container(border=True):
            st.metric("待解决", f"{unresolved_questions} 个插问")
            for question in unresolved_previews:
                st.caption(f"· {question}")
            _go_to_page(
                "回到插问",
                section_id="materials",
                page_id="ppt_tutor",
                key="dashboard_go_questions",
            )
    recommendation = _today_recommendation(
        _today_review_topics(today_tasks, limit=1),
        unresolved_questions,
    )
    st.caption(f"推荐行动：{recommendation}")

    if st.toggle("展开更多学习支持", value=False, key="dashboard_more_support"):
        _go_to_page(
            "整理知识卡片",
            section_id="knowledge",
            page_id="knowledge_cards",
            key="dashboard_go_cards",
        )

        st.subheader("课程概览")
        st.caption("课程状态一览")
        status_cols = st.columns(3)
        status_cols[0].metric(
            "学习中",
            int(status_counts.get("active", len(active_courses))),
        )
        status_cols[1].metric("已完成", int(status_counts.get("completed", 0)))
        status_cols[2].metric("归档", int(status_counts.get("archived", 0)))
        _go_to_page(
            "管理全部课程",
            section_id="today",
            page_id="course_center",
            key="dashboard_manage_courses",
        )

        low_cards = low_mastery_cards(user_id=user.id, include_archived=False)
        blockers = recent_blockers(user_id=user.id, include_archived=False)
        parking = open_parking_questions(user_id=user.id)
        links = recent_knowledge_links(user_id=user.id, include_archived=False)
        reminder_config = get_daily_reminder_config()
        review_log = get_today_review_log(user_id=user.id)
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
                    st.markdown(
                        f"**{task['subject']} · {task['topic']}**  "
                        f"{task['review_stage']} · 掌握度 {task['mastery']}%"
                    )
                    st.markdown(_self_test_question(task["topic"]))
        else:
            st.caption("今天没有到期复习任务。")

        left, right = st.columns(2)
        with left:
            st.markdown("**最近卡点**")
            if blockers:
                st.dataframe(
                    pd.DataFrame(blockers)[["date", "subject", "title", "blockers", "mastery"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("暂无卡点记录。")
        with right:
            st.markdown("**掌握度低于 70% 的知识点**")
            if low_cards:
                st.dataframe(
                    pd.DataFrame(low_cards)[["subject", "topic", "mastery", "core_question"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("暂无低掌握度知识点。")

        st.caption(f"知识双链 {len(links)} 条 · 探索停车场未解决 {len(parking)} 个")
        st.divider()
        _render_default_api_and_daily_ai_review()


def _current_learning_location(user_id: int, current_course: dict | None) -> dict | None:
    if not current_course:
        return None
    course_id = int(current_course["id"])
    active_context = get_active_context(user_id)
    deck_id = int(active_context.get("deck_id") or 0) if active_context.get("active") else 0
    deck = None
    if deck_id:
        deck = fetch_one(
            """
            SELECT id, title, slide_count
            FROM ppt_decks
            WHERE user_id = ? AND course_id = ? AND id = ?
            """,
            (user_id, course_id, deck_id),
        )
    if not deck:
        deck = fetch_one(
            """
            SELECT id, title, slide_count
            FROM ppt_decks
            WHERE user_id = ? AND course_id = ?
            ORDER BY sort_order ASC, created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, course_id),
        )
    if not deck:
        return None

    slide_number = 1
    if int(active_context.get("deck_id") or 0) == int(deck["id"]):
        slide_number = max(1, int(active_context.get("slide_number") or 1))
    slide_count = max(1, int(deck.get("slide_count") or 1))
    slide_number = min(slide_number, slide_count)
    section = fetch_one(
        """
        SELECT title
        FROM ppt_sections
        WHERE user_id = ? AND deck_id = ? AND start_slide <= ? AND end_slide >= ?
        ORDER BY section_index ASC
        LIMIT 1
        """,
        (user_id, int(deck["id"]), slide_number, slide_number),
    )
    return {
        "deck_id": int(deck["id"]),
        "deck_title": deck.get("title") or "未命名资料",
        "section_title": section.get("title") if section else "",
        "slide_number": slide_number,
        "slide_count": slide_count,
        "has_saved_position": bool(
            active_context.get("active")
            and int(active_context.get("deck_id") or 0) == int(deck["id"])
            and int(active_context.get("slide_number") or 0) > 0
        ),
    }


def _today_review_knowledge_count(tasks: list[dict]) -> int:
    return len(_distinct_review_knowledge(tasks))


def _today_review_topics(tasks: list[dict], *, limit: int = 3) -> list[str]:
    return [
        str(item.get("topic") or "未命名知识点")
        for item in _distinct_review_knowledge(tasks)[: max(0, int(limit))]
    ]


def _distinct_review_knowledge(tasks: list[dict]) -> list[dict]:
    distinct: list[dict] = []
    seen: set[object] = set()
    for index, task in enumerate(tasks):
        knowledge_id = task.get("knowledge_id")
        key: object = (
            ("id", int(knowledge_id))
            if knowledge_id not in (None, "")
            else (
                "topic",
                str(task.get("subject") or "").strip(),
                str(task.get("topic") or "").strip(),
                index if not str(task.get("topic") or "").strip() else "",
            )
        )
        if key in seen:
            continue
        seen.add(key)
        distinct.append(task)
    return distinct


def _unresolved_question_count(user_id: int, current_course: dict | None) -> int:
    if not current_course:
        return 0
    row = fetch_one(
        """
        SELECT COUNT(DISTINCT sq.id) AS count
        FROM slide_questions sq
        JOIN ppt_slides ps ON ps.id = sq.slide_id AND ps.user_id = sq.user_id
        JOIN ppt_decks d ON d.id = ps.deck_id AND d.user_id = sq.user_id
        WHERE sq.user_id = ? AND d.course_id = ?
          AND COALESCE(sq.understood, 0) = 0
          AND COALESCE(sq.converted_to_knowledge, 0) = 0
          AND COALESCE(sq.status, '') NOT IN ('已解决', '归档', 'closed', 'understood')
        """,
        (user_id, int(current_course["id"])),
    )
    return int(row.get("count") or 0) if row else 0


def _unresolved_question_previews(
    user_id: int,
    current_course: dict | None,
    *,
    limit: int = 3,
) -> list[str]:
    if not current_course:
        return []
    rows = fetch_all(
        """
        SELECT sq.question
        FROM slide_questions sq
        JOIN ppt_slides ps ON ps.id = sq.slide_id AND ps.user_id = sq.user_id
        JOIN ppt_decks d ON d.id = ps.deck_id AND d.user_id = sq.user_id
        WHERE sq.user_id = ? AND d.course_id = ?
          AND COALESCE(sq.understood, 0) = 0
          AND COALESCE(sq.converted_to_knowledge, 0) = 0
          AND COALESCE(sq.status, '') NOT IN ('已解决', '归档', 'closed', 'understood')
        ORDER BY sq.created_at ASC, sq.id ASC
        LIMIT ?
        """,
        (user_id, int(current_course["id"]), max(0, int(limit))),
    )
    return [str(row.get("question") or "未命名插问") for row in rows]


def _today_recommendation(review_topics: list[str], unresolved_questions: int) -> str:
    if review_topics:
        return f"先闭卷解释「{review_topics[0]}」，再完成对应复习。"
    if unresolved_questions:
        return "回到当前页插问，整理一个问题并转成知识卡。"
    return "完成当前章节总结，记录核心问题与下一步。"
