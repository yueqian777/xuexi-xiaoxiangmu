from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

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
from services.daily_ai_review_service import (
    answers_payload,
    collect_review_candidates,
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


def _self_test_question(topic: str) -> str:
    return f"请闭卷解释「{topic}」解决什么核心问题，并写出一句话解释、关键逻辑和一个典型应用。"


def _render_default_api_and_daily_ai_review() -> None:
    user = require_login()
    st.subheader("每日 AI 轻量复习")
    st.caption("先设置项目默认 API。首页会用少量问题检查今天最值得复习的知识点；提交答案后自动批改，并写回知识点掌握度。")

    providers = list_api_providers(enabled_only=True)
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

        candidates = collect_review_candidates(user_id=user.id)
        cols[1].metric("今日自测候选", len(candidates))
        if candidates:
            cols[2].caption("候选来自：今日到期复习、低于 70% 的知识点、仍需复习的知识卡片。")
        else:
            cols[2].caption("暂无候选知识点。先创建知识卡片或等待复习任务到期。")

    if not api_key and provider.get("auth_type") != "none" and not provider.get("api_key_env"):
        st.info("填写默认 API Key 后，首页会自动生成今天的轻量自测计划。")
        return

    plan = get_today_ai_review_plan(user_id=user.id)
    auto_key = f"daily_ai_review_auto_generated_{date.today().isoformat()}_{user.id}"
    if plan is None and candidates and not st.session_state.get(auto_key):
        st.session_state[auto_key] = True
        try:
            with st.spinner("正在自动生成今天的轻量复习提问..."):
                plan = generate_today_ai_review_plan(
                    provider_key=str(selected_provider_key),
                    api_key=api_key,
                    model=active_model,
                    max_output_tokens=int(max_tokens),
                    user_id=user.id,
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
                    user_id=user.id,
                )
            st.success("今日自测计划已更新。")
            st.rerun()
        except (AIServiceError, ValueError, RuntimeError) as exc:
            st.error(f"生成失败：{exc}")
    controls[1].caption("建议每天 3-5 题，不把复习变成负担。")

    plan = plan or get_today_ai_review_plan(user_id=user.id)
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
                st.markdown(
                    f"**{index}. [{question.get('question_type', '自测题')}] {question.get('topic', '')}**\n\n"
                    f"{question.get('question', '')}"
                )
                answers[question_id] = st.text_area(
                    "你的回答",
                    value=saved_answers.get(question_id, ""),
                    placeholder="先闭卷写。不会就留空或写“不会”，系统会按错因处理。",
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
            st.markdown(
                f"**{item.get('result')} · {item.get('score')} 分 · 错因：{item.get('cause_category')}**"
            )
            if item.get("feedback"):
                st.markdown(f"反馈：{item['feedback']}")
            if item.get("correct_answer"):
                st.markdown(f"参考答案：{item['correct_answer']}")
            if item.get("next_question"):
                st.caption(f"下一轮追问：{item['next_question']}")

    updates = evaluation.get("mastery_updates") or []
    if updates:
        st.markdown("**掌握度更新**")
        st.dataframe(pd.DataFrame(updates), use_container_width=True, hide_index=True)


def render() -> None:
    user = require_login()
    st.title("首页 Dashboard")
    st.caption("每天先看复习，再登记新学习，最后生成闭卷回忆 Prompt。")

    today_tasks = get_today_review_tasks(user_id=user.id)
    low_cards = low_mastery_cards(user_id=user.id)
    blockers = recent_blockers(user_id=user.id)
    parking = open_parking_questions(user_id=user.id)
    links = recent_knowledge_links(user_id=user.id)
    reminder_config = get_daily_reminder_config()
    review_log = get_today_review_log(user_id=user.id)

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

    _render_default_api_and_daily_ai_review()

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

    st.subheader("最近知识双链")
    if links:
        st.dataframe(
            pd.DataFrame(links)[
                [
                    "source_subject",
                    "source_topic",
                    "relation_type",
                    "target_topic",
                    "relation_note",
                    "created_at",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("暂无知识链接。可以在“知识点卡片”里把当前知识点连接到前置知识、相似概念或易混淆概念。")

    st.subheader("探索停车场问题")
    if parking:
        st.dataframe(
            pd.DataFrame(parking)[["subject", "question", "source", "status", "created_at"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("暂无未解决的扩展问题。")
