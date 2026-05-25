from __future__ import annotations

import base64
import html
import json
import os
import threading
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from db import BASE_DIR, execute, fetch_all, fetch_one, insert_and_get_id
from services.ai_service import (
    AIServiceError,
    DEFAULT_MODEL,
    generate_text,
    is_quota_error,
    list_api_providers,
    list_available_models,
    provider_label,
)
from services.api_key_ui import render_local_secret_unlock
from services.api_runtime import ensure_active_provider, ensure_provider_model, provider_model_state_key, set_active_provider
from services.auth_service import require_login
from services.ppt_service import import_deck, refresh_pdf_slide_text, render_missing_page_images
from services.prompt_service import render_template
from services.study_asset_service import parse_study_assets, save_study_assets

SYNCED_READER_COMPONENT_PATH = BASE_DIR / "components" / "synced_reader"
SYNCED_READER_COMPONENT = None
LAST_READER_POSITION_SETTING_KEY = "ppt_reader_last_position"
LAST_READER_DECK_STATE_KEY = "ppt_reader_deck_id"


def _get_synced_reader_component():
    global SYNCED_READER_COMPONENT
    if SYNCED_READER_COMPONENT is not None:
        return SYNCED_READER_COMPONENT
    if not SYNCED_READER_COMPONENT_PATH.exists():
        return None
    SYNCED_READER_COMPONENT = components.declare_component(
        "intp_synced_reader",
        path=str(SYNCED_READER_COMPONENT_PATH),
    )
    return SYNCED_READER_COMPONENT


def _read_last_reader_position(user_id: int) -> dict[str, int]:
    row = fetch_one(
        "SELECT value FROM app_settings WHERE key = ?",
        (f"user:{user_id}:{LAST_READER_POSITION_SETTING_KEY}",),
    )
    if not row:
        return {}
    try:
        data = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}

    position: dict[str, int] = {}
    for key in ("deck_id", "slide_number"):
        try:
            value = int(data.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            position[key] = value
    return position


def _save_last_reader_position(user_id: int, deck_id: int, slide_number: int | None = None) -> None:
    try:
        deck_id = int(deck_id)
    except (TypeError, ValueError):
        return
    if deck_id <= 0:
        return

    existing = _read_last_reader_position(user_id)
    if slide_number is None and existing.get("deck_id") == deck_id:
        slide_number = existing.get("slide_number")

    payload = {"deck_id": deck_id}
    try:
        slide_number_value = int(slide_number or 0)
    except (TypeError, ValueError):
        slide_number_value = 0
    if slide_number_value > 0:
        payload["slide_number"] = slide_number_value

    if existing == payload:
        return

    execute(
        """
        INSERT INTO app_settings (key, user_id, value, updated_at)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(key) DO UPDATE SET
            user_id = excluded.user_id,
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (f"user:{user_id}:{LAST_READER_POSITION_SETTING_KEY}", user_id, json.dumps(payload, ensure_ascii=False)),
    )


def _default_reader_deck_id(deck_ids: list[int], last_position: dict[str, int]) -> int:
    if not deck_ids:
        return 0

    remembered_deck_id = int(last_position.get("deck_id") or 0)
    if remembered_deck_id in deck_ids:
        return remembered_deck_id

    state_deck_id = st.session_state.get(LAST_READER_DECK_STATE_KEY)
    try:
        state_deck_id = int(state_deck_id or 0)
    except (TypeError, ValueError):
        state_deck_id = 0
    if state_deck_id in deck_ids:
        return state_deck_id

    return deck_ids[0]


def _remember_reader_deck_selection(user_id: int, deck_id: int, last_position: dict[str, int]) -> None:
    slide_number = None
    if last_position.get("deck_id") == deck_id:
        slide_number = last_position.get("slide_number")
    _save_last_reader_position(user_id, deck_id, slide_number)


def _initial_reader_slide_number(deck_id: int, slides: list[dict], last_position: dict[str, int]) -> int:
    if not slides:
        return 1
    slide_numbers = {int(slide["slide_number"]) for slide in slides}
    remembered_slide = int(last_position.get("slide_number") or 0)
    if int(last_position.get("deck_id") or 0) == int(deck_id) and remembered_slide in slide_numbers:
        return remembered_slide
    return int(slides[0]["slide_number"])


def render() -> None:
    user = require_login()
    st.title("PPT 逐页讲解")
    st.caption("边看 PPT 边让 GPT 按页讲解；插问单独进入浮窗，不覆盖当前页主线讲解。")

    _resume_interrupted_generation()
    _render_api_settings()
    decks = fetch_all(
        """
        SELECT *
        FROM ppt_decks
        WHERE user_id = ?
        ORDER BY
            CASE status
                WHEN '使用中' THEN 0
                WHEN '待整理' THEN 1
                WHEN '暂停' THEN 2
                WHEN '归档' THEN 3
                ELSE 9
            END,
            category ASC,
            sort_order ASC,
            created_at DESC,
            id DESC
        """,
        (user.id,),
    )
    _render_upload_form(expanded=not bool(decks))

    if not decks:
        st.info("请先上传一个 PPTX 或 PDF 文件。当前版本会解析每页文字内容，后续可继续增强真实页面渲染和 OCR。")
        return

    deck_by_id = {int(deck["id"]): deck for deck in decks}
    deck_ids = list(deck_by_id)
    last_position = _read_last_reader_position(user.id)
    default_deck_id = _default_reader_deck_id(deck_ids, last_position)
    if st.session_state.get(LAST_READER_DECK_STATE_KEY) not in deck_by_id:
        st.session_state[LAST_READER_DECK_STATE_KEY] = default_deck_id
    deck_id = st.selectbox(
        "选择 PPT",
        deck_ids,
        format_func=lambda item_id: _deck_label(deck_by_id, item_id),
        key=LAST_READER_DECK_STATE_KEY,
    )
    deck_id = int(deck_id)
    _remember_reader_deck_selection(user.id, deck_id, last_position)
    deck = deck_by_id.get(deck_id)
    slides = fetch_all(
        "SELECT * FROM ppt_slides WHERE user_id = ? AND deck_id = ? ORDER BY slide_number ASC",
        (user.id, deck_id),
    )
    if not deck or not slides:
        st.warning("这个 PPT 暂无可用页面，请重新上传。")
        return
    slide_by_id = {slide["id"]: slide for slide in slides}
    latest_by_slide_id = _latest_explanations_by_slide_ids(list(slide_by_id))

    st.divider()
    _render_deck_actions(deck, slides, latest_by_slide_id)
    _render_synced_reader(deck, slides, latest_by_slide_id, last_position)

    st.divider()
    _render_study_asset_generator(deck)


def _render_api_settings() -> None:
    with st.expander("AI API 设置", expanded=False):
        st.caption("选择任意已启用 Provider。API Key 只保存在当前 Streamlit 会话里，不写入 SQLite。")
        providers = list_api_providers(enabled_only=True)
        if not providers:
            st.warning("没有启用的 Provider。请先到「API 接入设置」页面创建。")
            return

        current_provider_key, _ = ensure_active_provider(providers)
        provider_keys = [provider["provider_key"] for provider in providers]
        selected_index = provider_keys.index(current_provider_key) if current_provider_key in provider_keys else 0
        provider_key = st.selectbox(
            "Provider",
            provider_keys,
            index=selected_index,
            format_func=lambda item_key: provider_label(next(p for p in providers if p["provider_key"] == item_key)),
        )
        provider = next(p for p in providers if p["provider_key"] == provider_key)
        ensure_provider_model(provider)

        key_name = f"api_key_provider_{provider_key}"
        render_local_secret_unlock(
            provider,
            model=provider.get("model") or DEFAULT_MODEL,
            target_session_key=key_name,
            key_prefix=f"ppt_provider_{provider_key}",
        )
        api_key = st.text_input(
            "临时 API Key",
            value=st.session_state.get(key_name, ""),
            type="password",
            placeholder=f"不填写则读取环境变量 {provider.get('api_key_env') or '未设置'}",
        )
        st.session_state[key_name] = api_key

        available_models = []
        if api_key or os.getenv(provider.get("api_key_env") or ""):
            available_models = list_available_models(provider, api_key=api_key)

        model_key = provider_model_state_key(provider_key)
        current_model = st.session_state.get(model_key, "").strip()
        if not current_model:
            current_model = provider.get("model") or DEFAULT_MODEL

        if available_models:
            model_index = 0
            if current_model in available_models:
                model_index = available_models.index(current_model)
            model = st.selectbox(
                "模型（已扫描）",
                available_models,
                index=model_index,
                key=model_key,
                help="已扫描到的可用模型。",
            )
            st.caption(f"✅ 已扫描到 {len(available_models)} 个可用模型")
        else:
            model = st.text_input(
                "当前 API 临时模型（未扫描到可用模型）",
                value=current_model,
                key=model_key,
                help="无法自动扫描此 Provider 的可用模型，请手动输入模型名称。",
            )
            st.caption("⚠️ 无法扫描到此 Provider 的可用模型列表，请手动填写模型名。")
        active_model = model.strip() or provider.get("model") or DEFAULT_MODEL
        set_active_provider(provider_key, active_model)
        max_tokens = st.number_input(
            "最大输出 token",
            min_value=512,
            max_value=16000,
            value=int(st.session_state.get("active_api_max_tokens", 4096)),
            step=512,
            help="DeepSeek V4 Pro 会消耗 reasoning token，建议至少 4096。",
        )
        st.session_state["active_api_max_tokens"] = int(max_tokens)
        reasoning_depth = st.selectbox(
            "推理深度",
            ["关闭", "低", "中", "高", "超高"],
            index=0,
            help="部分模型支持 extended thinking / reasoning_effort。开启后会消耗更多 token。",
        )
        st.session_state["active_api_reasoning_depth"] = reasoning_depth
        st.caption(f"当前 Base URL：{provider.get('base_url') or '未设置'}")
        st.caption("如果使用本地 CLIProxyAPI，默认客户端 Key 是 local-client-key；真实上游 Key 由代理服务保存。")


def _render_upload_form(*, expanded: bool = False) -> None:
    with st.expander("上传 PPT / PDF", expanded=expanded):
        st.caption("已有资料时默认折叠，减少逐页阅读和插问时的页面干扰。")
        with st.form("upload_pptx"):
            cols = st.columns(2)
            subject = cols[0].text_input("科目", placeholder="例如：信号与系统")
            title = cols[1].text_input("资料标题", placeholder="例如：第 3 章 Z 变换")
            uploaded = st.file_uploader("选择 PPTX 或 PDF 文件", type=["pptx", "pdf"])
            submitted = st.form_submit_button("导入资料")

    if submitted:
        if uploaded is None:
            st.error("请先选择 PPTX 或 PDF 文件。")
            return
        try:
            deck_id = import_deck(uploaded, subject=subject, title=title)
        except Exception as exc:
            st.error(f"资料导入失败：{exc}")
            return
        st.success(f"资料已导入，编号 #{deck_id}。")
        st.rerun()


def _render_deck_actions(deck: dict, slides: list[dict], latest_by_slide_id: dict[int, dict]) -> None:
    st.subheader("整份资料逐页分析")
    missing_images = [slide for slide in slides if not _image_exists(slide)]
    cols = st.columns([1.3, 1.3, 2])
    if cols[0].button("生成 / 修复原页面图片", disabled=not missing_images):
        try:
            with st.spinner("正在生成原页面图片..."):
                render_missing_page_images(deck, slides)
            st.success("原页面图片已生成。")
            st.rerun()
        except Exception as exc:
            st.error(f"生成原页面图片失败：{exc}")

    if _is_pdf_deck(deck):
        if st.button("重新提取 PDF 文字"):
            try:
                with st.spinner("正在重新提取 PDF 文字..."):
                    updated = refresh_pdf_slide_text(deck, slides)
                st.success(f"PDF 文字已刷新：{updated} 页提取到文本。")
                st.rerun()
            except Exception as exc:
                st.error(f"重新提取 PDF 文字失败：{exc}")

    only_missing = cols[1].checkbox("只生成缺失讲解", value=True)
    cols[2].caption("左侧滚动到某页时，右侧讲解会自动同步滚动到对应页。")
    input_mode = st.radio(
        "页面内容发送方式",
        ("文字优先，缺文字时发原图", "只用识别文字，不发原图", "直接发原图，不使用识别文字"),
        horizontal=True,
        help="公式、符号或扫描页识别不准时，可选择直接把原页面图片发给支持视觉输入的 API。",
        key=f"ppt_generation_input_mode_{deck['id']}",
    )
    send_image_when_no_text = input_mode != "只用识别文字，不发原图"
    force_image_input = input_mode == "直接发原图，不使用识别文字"
    supports_image_input = _active_provider_supports_image_input()
    if force_image_input and not supports_image_input:
        st.warning("当前 Provider / 模型看起来不支持图片输入。直接发原图模式无法生成；请切换视觉模型后再试。")
    elif send_image_when_no_text and not supports_image_input:
        st.warning("当前 Provider / 模型看起来不支持图片输入。空白扫描页会被跳过；请切换视觉模型，或重新导入可提取文字的 PDF。")
    selected_slides, range_label = _select_generation_range(slides)
    st.caption(f"当前生成范围：{range_label}；将逐页调用 API 并保存到右侧讲解区。")
    run_in_background = st.checkbox("后台运行（切换页面时继续生成）", value=True)
    if st.button("生成所选范围逐页讲解", type="primary"):
        _generate_whole_deck_explanations(
            deck,
            selected_slides,
            only_missing=only_missing,
            send_image_when_no_text=send_image_when_no_text,
            force_image_input=force_image_input,
            supports_image_input=supports_image_input,
            latest_by_slide_id=latest_by_slide_id,
            background=run_in_background,
        )


def _render_synced_reader(
    deck: dict,
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
    last_position: dict[str, int],
) -> None:
    st.subheader("同步阅读器")
    st.caption("提示：右侧固定插问栏会绑定当前页。你可以直接提问，或选中讲解文字后引用到插问。")
    question_by_slide_id = _questions_by_slide_ids([int(slide["id"]) for slide in slides])
    payload = _build_reader_payload(slides, latest_by_slide_id, question_by_slide_id)
    if not payload:
        st.warning("当前资料没有任何幻灯片数据。")
        return

    synced_reader_component = _get_synced_reader_component()
    if synced_reader_component is None:
        st.error(f"同步阅读器组件目录缺失：{SYNCED_READER_COMPONENT_PATH}")
        st.caption("请确认项目里的 components/synced_reader/index.html 存在，然后重启 Streamlit。")
        return

    component_payload = synced_reader_component(
        deck_id=int(deck["id"]),
        title=deck.get("title") or "学习资料",
        subject=deck.get("subject") or "未分类",
        active_model=_active_model_label(),
        pages=payload,
        initial_slide_number=_initial_reader_slide_number(int(deck["id"]), slides, last_position),
        height=850,
        default=None,
        key=f"synced_reader_{deck['id']}",
    )
    if isinstance(component_payload, dict):
        _handle_synced_reader_action(deck, slides, latest_by_slide_id, component_payload)


def _handle_synced_reader_action(
    deck: dict,
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
    payload: dict,
) -> None:
    action = payload.get("action")
    if action != "canvas_question":
        return
    try:
        query_deck_id = int(payload.get("deckId", 0))
        slide_number = int(payload.get("slideNumber", 0))
    except (TypeError, ValueError):
        return
    if query_deck_id != int(deck["id"]):
        return

    token = str(payload.get("token") or "").strip()
    last_token_key = f"ppt_canvas_question_last_token_{deck['id']}"
    if token and st.session_state.get(last_token_key) == token:
        return

    slide = next((item for item in slides if int(item["slide_number"]) == slide_number), None)
    question = str(payload.get("question") or "").strip()
    if not slide or not question:
        return

    quote_payload = payload.get("quote") if isinstance(payload.get("quote"), dict) else None
    quote = _quote_from_component_payload(deck, slide, quote_payload) if quote_payload else None
    full_question = _compose_quoted_branch_question(quote, question) if quote else question
    prompt = _build_branch_prompt(deck, slide, latest_by_slide_id.get(int(slide["id"])), full_question)
    try:
        with st.spinner(f"正在回答第 {slide_number} 页插问..."):
            answer = generate_text(
                prompt,
                provider_key=st.session_state.get("active_api_provider_key"),
                api_key=_active_api_key(),
                model_override=st.session_state.get("active_api_model", DEFAULT_MODEL),
                max_output_tokens=int(st.session_state.get("active_api_max_tokens", 4096)),
            )
        insert_and_get_id(
            """
            INSERT INTO slide_questions (user_id, slide_id, question, answer, model)
            VALUES (?, ?, ?, ?, ?)
            """,
            (require_login().id, slide["id"], full_question, answer, _active_model_label()),
        )
    except AIServiceError as exc:
        st.error(str(exc))
        st.caption("侧边插问调用失败，当前阅读位置不会被修改。")
        return

    if token:
        st.session_state[last_token_key] = token
    st.rerun()


def _quote_from_component_payload(deck: dict, slide: dict, payload: dict) -> dict | None:
    selected_text = str(payload.get("selectedText") or "").strip()
    if not selected_text:
        return None
    slide_number = int(slide["slide_number"])
    return {
        "deck_id": int(deck["id"]),
        "slide_id": int(slide["id"]),
        "slide_number": slide_number,
        "slide_title": str(payload.get("slideTitle") or slide.get("title") or f"第 {slide_number} 页"),
        "selected_text": selected_text,
        "context_before": str(payload.get("contextBefore", "")).strip(),
        "context_after": str(payload.get("contextAfter", "")).strip(),
        "token": str(payload.get("token") or f"{slide['id']}_{len(selected_text)}_{abs(hash(selected_text))}"),
    }


def _consume_branch_selection_from_query(deck: dict, slides: list[dict]) -> dict | None:
    params = st.query_params
    if params.get("intp_action") != "branch_quote":
        return st.session_state.get(_branch_quote_state_key(deck["id"]))

    try:
        query_deck_id = int(params.get("deck_id", "0"))
        slide_number = int(params.get("slide_number", "0"))
    except ValueError:
        return None
    if query_deck_id != int(deck["id"]):
        return None

    slide = next((item for item in slides if int(item["slide_number"]) == slide_number), None)
    selected_text = str(params.get("selected_text", "")).strip()
    if not slide or not selected_text:
        return None

    quote = {
        "deck_id": int(deck["id"]),
        "slide_id": int(slide["id"]),
        "slide_number": slide_number,
        "slide_title": slide.get("title") or f"第 {slide_number} 页",
        "selected_text": selected_text,
        "context_before": str(params.get("context_before", "")).strip(),
        "context_after": str(params.get("context_after", "")).strip(),
        "token": f"{slide['id']}_{len(selected_text)}_{abs(hash(selected_text))}",
    }
    st.session_state[_branch_quote_state_key(deck["id"])] = quote

    for key in [
        "intp_action",
        "deck_id",
        "slide_number",
        "selected_text",
        "context_before",
        "context_after",
    ]:
        if key in st.query_params:
            del st.query_params[key]
    return quote


def _branch_quote_state_key(deck_id: int) -> str:
    return f"ppt_branch_quote_{deck_id}"


def _select_generation_range(slides: list[dict]) -> tuple[list[dict], str]:
    mode = st.radio(
        "生成范围",
        ["全部生成", "10 页一组", "20 页一组"],
        horizontal=True,
        help="资料很长时建议分组生成，便于控制 API 消耗和失败重试。",
    )
    if mode == "全部生成":
        return slides, f"全部 {len(slides)} 页"

    group_size = 10 if mode == "10 页一组" else 20
    groups = _build_slide_groups(slides, group_size)
    selected_index = st.selectbox(
        "选择批次",
        list(range(len(groups))),
        format_func=lambda index: _group_label(groups[index]),
    )
    selected = groups[selected_index]
    return selected, _group_label(selected)


def _build_slide_groups(slides: list[dict], group_size: int) -> list[list[dict]]:
    return [slides[index : index + group_size] for index in range(0, len(slides), group_size)]


def _group_label(group: list[dict]) -> str:
    if not group:
        return "空批次"
    start = group[0]["slide_number"]
    end = group[-1]["slide_number"]
    return f"第 {start}-{end} 页（共 {len(group)} 页）"


def _render_study_asset_generator(deck: dict) -> None:
    with st.expander("学习沉淀：从今日阅读内容生成学习登记和知识卡片", expanded=False):
        _render_study_asset_generator_inner(deck)


def _render_study_asset_generator_inner(deck: dict) -> None:
    st.caption("根据当前资料里已识别文字和已生成讲解，调用当前 API 生成草稿；确认后写入学习登记、知识点卡片和 1-3-7-14 复习计划。")

    slides = _slides_with_latest_explanations(deck["id"])
    recognized = [slide for slide in slides if _slide_has_learning_content(slide)]
    today_slides = [slide for slide in recognized if _is_today(slide.get("explanation_created_at"))]
    if not recognized:
        st.info("当前资料还没有可沉淀的文字或讲解。请先重新提取 PDF 文字，或生成逐页讲解。")
        return

    source_options = []
    if today_slides:
        source_options.append("今天已生成讲解的页面")
    source_options.extend(["当前资料全部已识别页面", "当前资料按批次选择"])

    cols = st.columns([1.2, 1, 1])
    source_mode = cols[0].selectbox("内容来源", source_options, key=f"asset_source_mode_{deck['id']}")
    max_chars = cols[1].number_input(
        "最大输入字符",
        min_value=8000,
        max_value=60000,
        value=24000,
        step=2000,
        key=f"asset_max_chars_{deck['id']}",
        help="太长的 PPT 会超过模型上下文，建议先用 10 或 20 页批次生成。",
    )
    include_ai_explanation = cols[2].checkbox(
        "包含 AI 讲解",
        value=True,
        key=f"asset_include_ai_{deck['id']}",
        help="勾选后会把逐页讲解也作为沉淀依据；如果讲解质量不稳定，可以只用 PPT/PDF 识别文字。",
    )

    selected_slides = today_slides if source_mode == "今天已生成讲解的页面" else recognized
    range_label = source_mode
    if source_mode == "当前资料按批次选择":
        group_size = st.radio(
            "沉淀批次大小",
            [10, 20],
            horizontal=True,
            format_func=lambda value: f"{value} 页一组",
            key=f"asset_group_size_{deck['id']}",
        )
        groups = _build_slide_groups(recognized, int(group_size))
        group_index = st.selectbox(
            "选择要沉淀的批次",
            list(range(len(groups))),
            format_func=lambda index: _group_label(groups[index]),
            key=f"asset_group_index_{deck['id']}",
        )
        selected_slides = groups[group_index]
        range_label = _group_label(selected_slides)

    reading_content, used_pages, truncated = _build_reading_content(
        selected_slides,
        max_chars=int(max_chars),
        include_ai_explanation=include_ai_explanation,
    )
    st.caption(f"将用于生成：{range_label}；实际纳入 {used_pages} 页。{'内容过长，已截断。' if truncated else ''}")

    draft_key = f"study_asset_draft_{deck['id']}"
    raw_key = f"study_asset_raw_{deck['id']}"
    if st.button("调用 API 生成学习登记 / 知识卡片草稿", type="primary", key=f"generate_assets_{deck['id']}"):
        if not reading_content.strip():
            st.error("没有可发送给 API 的阅读内容。")
            return
        prompt = render_template(
            "ppt_to_study_assets.md",
            {
                "today": date.today().isoformat(),
                "subject": deck.get("subject") or "未分类",
                "deck_title": deck.get("title") or "未命名资料",
                "range_label": range_label,
                "reading_content": reading_content,
            },
        )
        try:
            with st.spinner("正在调用 API 生成结构化学习资产..."):
                output = generate_text(
                    prompt,
                    provider_key=st.session_state.get("active_api_provider_key"),
                    api_key=_active_api_key(),
                    model_override=st.session_state.get("active_api_model", DEFAULT_MODEL),
                    max_output_tokens=int(st.session_state.get("active_api_max_tokens", 4096)),
                )
            assets = parse_study_assets(output)
            st.session_state[draft_key] = assets
            st.session_state[raw_key] = output
            st.success("草稿已生成，请先预览再写入数据库。")
        except (AIServiceError, ValueError, json.JSONDecodeError) as exc:
            st.error(f"生成或解析失败：{exc}")
            if "output" in locals():
                st.caption("API 原始返回：")
                st.code(output, language="json")

    draft = st.session_state.get(draft_key)
    if not draft:
        return

    with st.expander("预览将写入的学习登记和知识卡片", expanded=True):
        st.json(draft)
        cols = st.columns(2)
        if cols[0].button("确认写入学习登记和知识卡片", key=f"save_assets_{deck['id']}"):
            try:
                session_id, knowledge_ids = save_study_assets(
                    draft,
                    fallback_subject=deck.get("subject") or "未分类",
                    fallback_chapter=deck.get("title") or "",
                )
            except Exception as exc:
                st.error(f"写入失败：{exc}")
                return
            st.success(f"已写入学习记录 #{session_id}，知识点卡片 {len(knowledge_ids)} 张，并已生成复习计划。")
            del st.session_state[draft_key]
            st.rerun()
        if cols[1].button("清除草稿", key=f"clear_assets_{deck['id']}"):
            del st.session_state[draft_key]
            st.session_state.pop(raw_key, None)
            st.rerun()


def _slides_with_latest_explanations(deck_id: int) -> list[dict]:
    user_id = require_login().id
    return fetch_all(
        """
        SELECT
            ps.*,
            se.explanation AS latest_explanation,
            se.model AS latest_model,
            se.created_at AS explanation_created_at
        FROM ppt_slides ps
        LEFT JOIN slide_explanations se
            ON se.id = (
                SELECT id
                FROM slide_explanations
                WHERE user_id = ps.user_id AND slide_id = ps.id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            )
        WHERE ps.user_id = ? AND ps.deck_id = ?
        ORDER BY ps.slide_number ASC
        """,
        (user_id, deck_id),
    )


def _slide_has_learning_content(slide: dict) -> bool:
    return bool((slide.get("slide_text") or "").strip() or (slide.get("latest_explanation") or "").strip())


def _is_today(value: str | None) -> bool:
    return bool(value and value[:10] == date.today().isoformat())


def _build_reading_content(
    slides: list[dict],
    *,
    max_chars: int,
    include_ai_explanation: bool,
) -> tuple[str, int, bool]:
    chunks: list[str] = []
    used_pages = 0
    truncated = False
    current_chars = 0

    for slide in slides:
        slide_text = (slide.get("slide_text") or "").strip()
        explanation = (slide.get("latest_explanation") or "").strip() if include_ai_explanation else ""
        if not slide_text and not explanation:
            continue

        chunk = "\n".join(
            part
            for part in [
                f"## 第 {slide['slide_number']} 页：{slide.get('title') or '未命名页面'}",
                f"PPT/PDF 识别文字：\n{_clip_text(slide_text, 2200)}" if slide_text else "",
                f"已生成 AI 讲解：\n{_clip_text(explanation, 2600)}" if explanation else "",
            ]
            if part
        )
        extra_chars = len(chunk) + (2 if chunks else 0)
        if current_chars + extra_chars > max_chars:
            truncated = True
            if not chunks:
                chunks.append(chunk[:max_chars] + "\n[内容已因长度限制截断]")
                used_pages += 1
            break
        chunks.append(chunk)
        current_chars += extra_chars
        used_pages += 1

    return "\n\n".join(chunks).strip(), used_pages, truncated


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[本页内容已截断]"


def _render_main_explanation(deck: dict, slide: dict) -> None:
    st.subheader("当前页主线讲解")
    latest = _latest_explanation(slide["id"])
    supports_image_input = _active_provider_supports_image_input()
    force_image_input = st.checkbox(
        "本页直接发原图给 API，不使用识别文字",
        value=False,
        help="适合公式、符号或版式复杂页面。需要当前 Provider / 模型支持图片输入。",
        key=f"ppt_current_force_image_{slide['id']}",
    )
    image_paths = (
        _image_paths_for_generation(
            slide,
            True,
            supports_image_input=supports_image_input,
            force_image_input=force_image_input,
        )
        if force_image_input
        else []
    )
    if force_image_input and not supports_image_input:
        st.warning("当前 Provider / 模型看起来不支持图片输入。请切换视觉模型后再直接发原图。")
    elif force_image_input and not image_paths:
        st.warning("本页还没有可用原页面图片。请先点击上方“生成 / 修复原页面图片”。")
    prompt = _build_slide_prompt(
        deck,
        slide,
        image_attached=bool(image_paths),
        ignore_extracted_text=force_image_input,
    )

    cols = st.columns(2)
    generate = cols[0].button("生成 / 更新本页讲解", type="primary")
    show_prompt = cols[1].toggle("显示本页讲解 Prompt", value=False)

    if show_prompt:
        st.code(prompt, language="markdown")

    if generate and force_image_input and not image_paths:
        st.warning("直接发原图模式需要支持图片输入的模型和已生成的原页面图片，本次没有调用 API。")
    elif generate:
        try:
            with st.spinner("GPT 正在按当前页生成主线讲解..."):
                explanation = generate_text(
                    prompt,
                    provider_key=st.session_state.get("active_api_provider_key"),
                    api_key=_active_api_key(),
                    model_override=st.session_state.get("active_api_model", DEFAULT_MODEL),
                    image_paths=image_paths,
                    max_output_tokens=int(st.session_state.get("active_api_max_tokens", 4096)),
                    reasoning_depth=st.session_state.get("active_api_reasoning_depth"),
                )
            insert_and_get_id(
                """
                INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
                VALUES (?, ?, ?, ?)
                """,
                (require_login().id, slide["id"], _active_model_label(), explanation),
            )
            st.success("本页主线讲解已保存。")
            st.rerun()
        except AIServiceError as exc:
            st.error(str(exc))
            st.caption("可以先复制下面的 Prompt 到 ChatGPT 手动使用。")
            st.code(prompt, language="markdown")

    latest = _latest_explanation(slide["id"])
    if latest:
        st.markdown(latest["explanation"])
        st.caption(f"模型：{latest['model']} · 生成时间：{latest['created_at']}")
    else:
        st.info("还没有生成本页主线讲解。点击上方按钮，或先复制 Prompt 到 ChatGPT。")


def _render_branch_popover(
    deck: dict,
    slide: dict,
    quote: dict | None = None,
    latest: dict | None = None,
) -> None:
    if latest is None:
        latest = _latest_explanation(slide["id"])
    if quote:
        with st.container(border=True):
            st.subheader("基于选中文本插问")
            st.caption(f"已引用第 {quote['slide_number']} 页 · {quote['slide_title']}。回答会保存为本页插问，不覆盖主线讲解。")
            _render_branch_question_form(deck, slide, latest, quote=quote, form_key_suffix=quote["token"])

    with st.popover("打开插问浮窗：问问题但不覆盖主线讲解", use_container_width=True):
        st.markdown(f"**当前锚点：第 {slide['slide_number']} 页 · {slide['title']}**")
        st.caption("这里的回答会保存到插问记录，不会覆盖右侧的主线讲解。")
        _render_branch_question_form(deck, slide, latest, quote=None, form_key_suffix="manual")


def _render_branch_question_form(
    deck: dict,
    slide: dict,
    latest: dict | None,
    *,
    quote: dict | None,
    form_key_suffix: str,
) -> None:
    if quote:
        st.text_area(
            "引用内容",
            value=quote["selected_text"],
            height=110,
            disabled=True,
            key=f"quote_preview_{slide['id']}_{form_key_suffix}",
        )
        with st.expander("自动保留的前后文", expanded=False):
            st.markdown("**前文**")
            st.text(quote.get("context_before") or "无")
            st.markdown("**后文**")
            st.text(quote.get("context_after") or "无")

    with st.form(f"branch_question_{slide['id']}_{form_key_suffix}", clear_on_submit=True):
        question = st.text_area(
            "我的插问",
            value="请解释这段引用的含义，并说明它和本页主线的关系。" if quote else "",
            placeholder="例如：这一页里的 ROC 为什么会影响反变换？",
            height=140,
        )
        submitted = st.form_submit_button("问当前模型")

    if not submitted:
        return
    if not question.strip():
        st.error("插问不能为空。")
        return

    full_question = _compose_quoted_branch_question(quote, question.strip()) if quote else question.strip()
    prompt = _build_branch_prompt(deck, slide, latest, full_question)
    try:
        with st.spinner("GPT 正在回答插问..."):
            answer = generate_text(
                prompt,
                provider_key=st.session_state.get("active_api_provider_key"),
                api_key=_active_api_key(),
                model_override=st.session_state.get("active_api_model", DEFAULT_MODEL),
                max_output_tokens=int(st.session_state.get("active_api_max_tokens", 4096)),
                reasoning_depth=st.session_state.get("active_api_reasoning_depth"),
            )
        insert_and_get_id(
            """
            INSERT INTO slide_questions (user_id, slide_id, question, answer, model)
            VALUES (?, ?, ?, ?, ?)
            """,
            (require_login().id, slide["id"], full_question, answer, _active_model_label()),
        )
        if quote:
            st.session_state.pop(_branch_quote_state_key(quote["deck_id"]), None)
        st.success(f"插问已保存。现在回到第 {slide['slide_number']} 页主线。")
        st.rerun()
    except AIServiceError as exc:
        st.error(str(exc))
        st.caption("可以先复制下面的插问 Prompt 到 ChatGPT 手动使用。")
        st.code(prompt, language="markdown")


def _compose_quoted_branch_question(quote: dict, question: str) -> str:
    return "\n".join(
        [
            f"我选中了第 {quote['slide_number']} 页的一段内容，想围绕这段话插问。",
            "",
            "引用内容：",
            quote["selected_text"],
            "",
            "前文上下文：",
            quote.get("context_before") or "无",
            "",
            "后文上下文：",
            quote.get("context_after") or "无",
            "",
            "我的问题：",
            question,
        ]
    )


def _render_question_history(slide_id: int) -> None:
    questions = fetch_all(
        """
        SELECT question, answer, model, category, status, sort_order, created_at
        FROM slide_questions
        WHERE slide_id = ?
        ORDER BY sort_order ASC, created_at ASC, id ASC
        """,
        (slide_id,),
    )
    st.subheader("本页插问记录")
    if not questions:
        st.caption("当前页还没有插问。")
        return
    for item in questions:
        with st.container(border=True):
            st.markdown(f"**问：** {item['question']}")
            st.markdown(item["answer"])
            st.caption(
                f"分类：{item.get('category') or '未分类'} · 状态：{item.get('status') or '未整理'} · "
                f"排序：{item.get('sort_order') or 0} · 模型：{item['model']} · {item['created_at']}"
            )

    with st.expander("表格视图"):
        st.dataframe(pd.DataFrame(questions), use_container_width=True, hide_index=True)


def _resume_interrupted_generation() -> None:
    task = st.session_state.get("ppt_generation_task")
    if not task:
        return

    status = task.get("status")
    stop_requested = task.get("stop_requested")

    # 处理停止请求：用户点击停止时立即更新状态，不等后台线程
    if stop_requested and status == "running":
        task["status"] = "stopped"
        task["status_text"] = task.get("status_text", "生成已停止")
        status = "stopped"

    if status == "completed":
        st.success(f"✅ 生成完成：{task['generated']} 页")
        return
    if status == "stopped":
        st.warning(f"⚠️ 已停止：{task.get('status_text', '生成已中断')}")
        return
    if status != "running":
        return

    col1, col2 = st.columns([1, 0.15])
    with col1:
        st.info("⏳ 后台生成进行中...")
        st.progress(task["progress"], text=task.get("status_text", "生成中..."))
    with col2:
        if st.button("停止", key="stop_generation"):
            task["stop_requested"] = True
            st.rerun()
            return

    # 后台任务进行中时，周期性触发重新渲染以更新进度
    import time
    time.sleep(1.5)
    st.rerun()


def _generate_whole_deck_explanations(
    deck: dict,
    slides: list[dict],
    *,
    only_missing: bool,
    send_image_when_no_text: bool,
    force_image_input: bool,
    supports_image_input: bool,
    latest_by_slide_id: dict[int, dict],
    background: bool = False,
) -> None:
    targets = []
    for slide in slides:
        latest = latest_by_slide_id.get(int(slide["id"]))
        if only_missing and latest:
            continue
        targets.append(slide)

    if not targets:
        st.info("所有页面都已有讲解。")
        return

    provider_key = st.session_state.get("active_api_provider_key")
    api_key = _active_api_key()
    active_model = st.session_state.get("active_api_model", DEFAULT_MODEL)
    max_tokens = int(st.session_state.get("active_api_max_tokens", 4096))
    active_model_label = _active_model_label()
    total = len(targets)

    if background:
        task = {
            "status": "running",
            "progress": 0.0,
            "status_text": f"正在分析第 1 页 / 共 {total} 页待生成...",
            "generated": 0,
            "deck_id": int(deck["id"]),
            "targets": [int(s["id"]) for s in targets],
            "only_missing": only_missing,
            "send_image_when_no_text": send_image_when_no_text,
            "force_image_input": force_image_input,
            "supports_image_input": supports_image_input,
            "provider_key": provider_key,
            "api_key": api_key,
            "active_model": active_model,
            "max_tokens": max_tokens,
            "active_model_label": active_model_label,
            "completed": False,
            "stop_requested": False,
        }
        st.session_state["ppt_generation_task"] = task
        thread = threading.Thread(
            target=_background_generation_worker,
            args=(task, deck, targets),
            daemon=True,
        )
        thread.start()
        st.rerun()
        return

    progress = st.progress(0, text="准备生成逐页讲解...")
    generated = 0
    skipped = 0
    for index, slide in enumerate(targets, start=1):
        image_paths = _image_paths_for_generation(
            slide,
            send_image_when_no_text,
            supports_image_input=supports_image_input,
            force_image_input=force_image_input,
        )
        if force_image_input and not image_paths:
            st.warning(f"第 {slide['slide_number']} 页直接发原图模式没有可用图片，或当前模型不能读图片，已跳过。")
            skipped += 1
            continue
        if _is_text_empty(slide) and not image_paths:
            st.warning(f"第 {slide['slide_number']} 页没有提取到文字，且当前模型不能读图片，已跳过。")
            skipped += 1
            continue
        prompt = _build_slide_prompt(
            deck,
            slide,
            image_attached=bool(image_paths),
            ignore_extracted_text=force_image_input,
        )
        try:
            progress.progress(
                (index - 1) / len(targets),
                text=f"正在分析第 {slide['slide_number']} 页 / 共 {len(targets)} 页待生成...",
            )
            explanation = generate_text(
                prompt,
                provider_key=provider_key,
                api_key=api_key,
                model_override=active_model,
                image_paths=image_paths,
                max_output_tokens=max_tokens,
                reasoning_depth=st.session_state.get("active_api_reasoning_depth"),
            )
            insert_and_get_id(
                """
                INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
                VALUES (?, ?, ?, ?)
                """,
                (require_login().id, slide["id"], active_model_label, explanation),
            )
            generated += 1
        except AIServiceError as exc:
            if image_paths and _is_image_input_error(exc):
                if force_image_input:
                    st.error(f"第 {slide['slide_number']} 页：当前模型拒绝图片输入。直接发原图模式不会自动回退识别文字，已停止。")
                    break
                st.warning(f"第 {slide['slide_number']} 页：当前模型拒绝图片输入，已自动改为文本模式重试。")
                if _is_text_empty(slide):
                    st.warning(f"第 {slide['slide_number']} 页没有可用文字，文本模式无法生成有效讲解，已跳过。")
                    skipped += 1
                    continue
                try:
                    explanation = generate_text(
                        _build_slide_prompt(deck, slide, image_attached=False),
                        provider_key=provider_key,
                        api_key=api_key,
                        model_override=active_model,
                        max_output_tokens=max_tokens,
                        reasoning_depth=st.session_state.get("active_api_reasoning_depth"),
                    )
                    insert_and_get_id(
                        """
                        INSERT INTO slide_explanations (slide_id, model, explanation)
                        VALUES (?, ?, ?)
                        """,
                        (slide["id"], active_model_label, explanation),
                    )
                    generated += 1
                    continue
                except AIServiceError as retry_exc:
                    st.error(f"第 {slide['slide_number']} 页文本模式重试失败：{retry_exc}")
                    break
            if is_quota_error(exc):
                st.error(f"第 {slide['slide_number']} 页生成失败：{exc}")
                st.info("检测到 API 额度或上游余额不足，已停止后续页面生成。请切换 Provider、充值上游接口，或更换可用模型后再继续。")
                break
            st.error(f"第 {slide['slide_number']} 页生成失败：{exc}")
            break
    progress.progress(1.0, text=f"已生成 {generated} 页讲解，跳过 {skipped} 页。")
    if generated:
        st.success(f"逐页讲解已保存：{generated} 页。")
        st.rerun()
    elif skipped:
        st.info("没有生成新讲解。被跳过的页面需要可提取文字、OCR，或支持图片输入的视觉模型。")


def _background_generation_worker(task: dict, deck: dict, targets: list[dict]) -> None:
    from services.ai_service import AIServiceError, generate_text
    skipped = 0
    total = len(targets)
    reasoning_depth = st.session_state.get("active_api_reasoning_depth")

    for index, slide in enumerate(targets, start=1):
        if task.get("stop_requested"):
            task["status"] = "stopped"
            task["status_text"] = f"已停止：{index - 1} 页"
            return
        task["progress"] = (index - 1) / total
        task["status_text"] = f"正在分析第 {slide['slide_number']} 页 / 共 {total} 页待生成..."

        from pages.ppt_tutor import _is_text_empty, _image_paths_for_generation, _build_slide_prompt
        image_paths = _image_paths_for_generation(
            slide,
            task["send_image_when_no_text"],
            supports_image_input=task["supports_image_input"],
            force_image_input=task.get("force_image_input", False),
        )
        if task.get("force_image_input") and not image_paths:
            skipped += 1
            continue
        if _is_text_empty(slide) and not image_paths:
            skipped += 1
            continue
        prompt = _build_slide_prompt(
            deck,
            slide,
            image_attached=bool(image_paths),
            ignore_extracted_text=task.get("force_image_input", False),
        )
        try:
            explanation = generate_text(
                prompt,
                provider_key=task["provider_key"],
                api_key=task["api_key"],
                model_override=task["active_model"],
                image_paths=image_paths,
                max_output_tokens=task["max_tokens"],
                reasoning_depth=reasoning_depth,
            )
            insert_and_get_id(
                """
                INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
                VALUES (?, ?, ?, ?)
                """,
                (require_login().id, slide["id"], task["active_model_label"], explanation),
            )
        except AIServiceError:
            pass

    task["status"] = "completed"
    task["progress"] = 1.0
    task["generated"] = len(targets) - skipped
    task["status_text"] = f"生成完成：{task['generated']} 页"


def _build_reader_payload(
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
    question_by_slide_id: dict[int, list[dict]],
) -> list[dict]:
    payload = []
    for slide in slides:
        image_path = Path(slide.get("image_path") or "")
        latest = latest_by_slide_id.get(int(slide["id"]))
        slide_text = slide.get("slide_text") or ""
        slide_title = slide.get("title") or f"第 {slide['slide_number']} 页"

        if image_path.exists() and image_path.is_file():
            image_data = _image_data_uri(image_path)
        else:
            image_data = ""

        payload.append(
            {
                "slideNumber": int(slide["slide_number"]),
                "title": slide_title,
                "image": image_data,
                "explanation": latest["explanation"] if latest else "本页还没有 AI 讲解。" + (f"\n\n参考文字：\n{slide_text[:200]}..." if slide_text else ""),
                "model": latest["model"] if latest else "",
                "createdAt": latest["created_at"] if latest else "",
                "questions": question_by_slide_id.get(int(slide["id"]), []),
            }
        )
    return payload


def _build_synced_reader_html(deck: dict, payload: list[dict]) -> str:
    pages_json = json.dumps(payload, ensure_ascii=False)
    deck_id = int(deck["id"])
    title = html.escape(deck.get("title") or "学习资料")
    subject = html.escape(deck.get("subject") or "未分类")
    active_model = html.escape(_active_model_label())
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
        displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
        processEscapes: true
      }},
      options: {{
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      }},
      startup: {{
        typeset: false
      }}
    }};
  </script>
  <script src="https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
  <style>
    :root {{
      --bg: #f6f1e8;
      --ink: #20201d;
      --muted: #706b61;
      --line: #ded4c5;
      --accent: #9a4f23;
      --panel: #fffaf0;
      --shadow: rgba(56, 38, 18, 0.14);
    }}
    * {{ box-sizing: border-box; }}
    html {{
      height: 100%;
      overflow: hidden;
      overscroll-behavior: none;
    }}
    body {{
      margin: 0;
      height: 100%;
      overflow: hidden;
      background: linear-gradient(135deg, #f7efe3, #eee5d4);
      color: var(--ink);
      font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif;
      overscroll-behavior: none;
    }}
    .frame {{
      height: 835px;
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      background: var(--bg);
      box-shadow: 0 18px 45px var(--shadow);
    }}
    .topbar {{
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      background: rgba(255, 250, 240, 0.94);
      border-bottom: 1px solid var(--line);
    }}
    .title {{
      font-weight: 800;
      letter-spacing: 0.02em;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
    }}
    .current {{
      color: var(--accent);
      font-weight: 800;
    }}
    .grid {{
      height: calc(100% - 58px);
      display: grid;
      grid-template-columns: minmax(0, 1.22fr) minmax(360px, 0.78fr);
    }}
    .pages, .notes {{
      height: 100%;
      overflow-y: auto;
      scroll-behavior: smooth;
      overscroll-behavior: contain;
      touch-action: pan-y;
    }}
    .pages {{
      padding: 22px 24px 80px;
      background:
        radial-gradient(circle at 10% 10%, rgba(154,79,35,.08), transparent 28%),
        #eee6d7;
      border-right: 1px solid var(--line);
    }}
    .page {{
      margin: 0 auto 30px;
      max-width: 960px;
      padding: 12px;
      border-radius: 14px;
      border: 2px solid transparent;
      background: rgba(255,255,255,.56);
      box-shadow: 0 10px 28px rgba(48,34,17,.16);
      transition: border-color .18s, transform .18s, box-shadow .18s;
    }}
    .page.active {{
      border-color: var(--accent);
      transform: translateY(-2px);
      box-shadow: 0 16px 38px rgba(120,70,28,.26);
    }}
    .page-label {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 2px 4px 10px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 700;
    }}
    .page img {{
      width: 100%;
      display: block;
      border-radius: 8px;
      background: #fff;
    }}
    .notes {{
      padding: 22px 20px 80px;
      background: var(--panel);
    }}
    .note {{
      min-height: 260px;
      margin: 0 0 22px;
      padding: 18px 18px 20px;
      border: 1px solid var(--line);
      border-left: 5px solid transparent;
      border-radius: 16px;
      background: #fffdf7;
      box-shadow: 0 8px 18px rgba(70,45,18,.08);
      transition: border-color .18s, background .18s;
      line-height: 1.72;
      font-size: 15px;
    }}
    .note.active {{
      border-left-color: var(--accent);
      background: #fff7e8;
    }}
    .note h3 {{
      margin: 0 0 10px;
      color: var(--accent);
      font-size: 18px;
    }}
    .note-meta {{
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 12px;
    }}
    .note-body {{
      overflow-wrap: anywhere;
    }}
    .note-body h1,
    .note-body h2,
    .note-body h3,
    .note-body h4 {{
      margin: 16px 0 8px;
      color: #7f3f1a;
      line-height: 1.35;
    }}
    .note-body h1 {{ font-size: 21px; }}
    .note-body h2 {{ font-size: 19px; }}
    .note-body h3 {{ font-size: 17px; }}
    .note-body p {{
      margin: 8px 0;
    }}
    .note-body ul,
    .note-body ol {{
      margin: 8px 0 10px;
      padding-left: 24px;
    }}
    .note-body li {{
      margin: 4px 0;
    }}
    .note-body blockquote {{
      margin: 12px 0;
      padding: 8px 12px;
      border-left: 4px solid #c98245;
      background: #fff3df;
      color: #5c5144;
    }}
    .note-body pre {{
      margin: 12px 0;
      padding: 12px;
      overflow-x: auto;
      border-radius: 10px;
      background: #28231d;
      color: #f9efe0;
      line-height: 1.55;
    }}
    .note-body code {{
      padding: 2px 5px;
      border-radius: 5px;
      background: #efe2cd;
      color: #6f3718;
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 0.92em;
    }}
    .note-body pre code {{
      padding: 0;
      background: transparent;
      color: inherit;
    }}
    .note-body table {{
      width: 100%;
      margin: 12px 0;
      border-collapse: collapse;
      display: block;
      overflow-x: auto;
      font-size: 14px;
    }}
    .note-body th,
    .note-body td {{
      border: 1px solid #dbc8ac;
      padding: 7px 9px;
      text-align: left;
      vertical-align: top;
    }}
    .note-body th {{
      background: #f2dfbf;
      color: #653314;
    }}
    .note-body hr {{
      border: 0;
      border-top: 1px solid var(--line);
      margin: 16px 0;
    }}
    .note-body mjx-container {{
      overflow-x: auto;
      overflow-y: hidden;
      max-width: 100%;
      padding: 2px 0;
    }}
    .selection-toolbar {{
      position: fixed;
      z-index: 9999;
      display: none;
      align-items: center;
      gap: 8px;
      max-width: min(560px, calc(100vw - 24px));
      padding: 9px 10px;
      border: 1px solid rgba(86, 48, 18, 0.18);
      border-radius: 999px;
      background: rgba(38, 27, 16, 0.94);
      color: #fff8ea;
      box-shadow: 0 12px 34px rgba(24, 14, 5, 0.28);
      font-size: 13px;
    }}
    .selection-toolbar.show {{
      display: flex;
    }}
    .selection-toolbar button {{
      border: 0;
      border-radius: 999px;
      padding: 7px 11px;
      background: #f0b35f;
      color: #2d1a0c;
      font-weight: 800;
      cursor: pointer;
      white-space: nowrap;
    }}
    .selection-toolbar button.secondary {{
      background: rgba(255, 255, 255, 0.14);
      color: #fff8ea;
    }}
    .selection-toolbar span {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: #e8d8bf;
    }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .notes {{ display: none; }}
      .pages {{ border-right: 0; }}
    }}
  </style>
</head>
<body>
  <div class="frame">
    <div class="topbar">
      <div>
        <div class="title">{title}</div>
        <div class="meta">{subject} · 原页面同步阅读</div>
      </div>
      <div class="current" id="currentPage">第 1 页</div>
    </div>
    <div class="grid">
      <section class="pages" id="pages"></section>
      <aside class="notes" id="notes"></aside>
    </div>
  </div>
  <div class="selection-toolbar" id="selectionToolbar">
    <button type="button" id="askSelectionButton">引用到插问</button>
    <button type="button" class="secondary" id="copySelectionButton">复制引用</button>
    <span id="selectionHint">将引用选中文本，并用当前模型：{active_model}</span>
  </div>
  <script>
    const deckId = {deck_id};
    const pages = {pages_json};
    const pageRoot = document.getElementById('pages');
    const noteRoot = document.getElementById('notes');
    const current = document.getElementById('currentPage');
    const selectionToolbar = document.getElementById('selectionToolbar');
    const askSelectionButton = document.getElementById('askSelectionButton');
    const copySelectionButton = document.getElementById('copySelectionButton');
    const selectionHint = document.getElementById('selectionHint');
    let currentSelectionPayload = null;

    function escapeHtml(value) {{
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }}

    function renderMarkdown(value) {{
      const source = String(value ?? '');
      if (!window.marked || !window.DOMPurify) {{
        return escapeHtml(source).replaceAll('\\n', '<br>');
      }}
      const rawHtml = window.marked.parse(source, {{
        gfm: true,
        breaks: true
      }});
      return window.DOMPurify.sanitize(rawHtml, {{
        USE_PROFILES: {{ html: true }}
      }});
    }}

    pageRoot.innerHTML = pages.map(page => `
      <article class="page" id="page-${{page.slideNumber}}" data-page="${{page.slideNumber}}">
        <div class="page-label">
          <span>第 ${{page.slideNumber}} 页</span>
          <span>${{escapeHtml(page.title)}}</span>
        </div>
        <img src="${{page.image}}" alt="第 ${{page.slideNumber}} 页原页面" loading="lazy" />
      </article>
    `).join('');

    noteRoot.innerHTML = pages.map(page => `
      <article class="note" id="note-${{page.slideNumber}}" data-page="${{page.slideNumber}}">
        <h3>第 ${{page.slideNumber}} 页讲解</h3>
        <div class="note-meta">${{escapeHtml(page.model || '未生成')}} ${{page.createdAt ? '· ' + escapeHtml(page.createdAt) : ''}}</div>
        <div class="note-body">${{renderMarkdown(page.explanation)}}</div>
      </article>
    `).join('');

    function typesetMath() {{
      if (!window.MathJax?.typesetPromise) {{
        window.setTimeout(typesetMath, 120);
        return;
      }}
      window.MathJax.typesetPromise([noteRoot]).catch(error => console.error(error));
    }}
    typesetMath();

    function setActive(pageNumber) {{
      document.querySelectorAll('.page.active,.note.active').forEach(el => el.classList.remove('active'));
      const page = document.getElementById(`page-${{pageNumber}}`);
      const note = document.getElementById(`note-${{pageNumber}}`);
      if (page) page.classList.add('active');
      if (note) {{
        note.classList.add('active');
        noteRoot.scrollTo({{ top: note.offsetTop - noteRoot.offsetTop, behavior: 'smooth' }});
      }}
      current.textContent = `第 ${{pageNumber}} 页`;
    }}

    const observer = new IntersectionObserver((entries) => {{
      const visible = entries
        .filter(entry => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      setActive(visible.target.dataset.page);
    }}, {{
      root: pageRoot,
      threshold: [0.35, 0.5, 0.65, 0.8]
    }});

    document.querySelectorAll('.page').forEach(page => observer.observe(page));
    if (pages.length) setActive(pages[0].slideNumber);

    function clipText(value, limit) {{
      const text = String(value ?? '').replace(/\\s+/g, ' ').trim();
      if (text.length <= limit) return text;
      return text.slice(0, limit).trim() + '...';
    }}

    function nodeElement(node) {{
      if (!node) return null;
      return node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    }}

    function buildSelectionPayload() {{
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
      const selectedText = selection.toString().trim();
      if (selectedText.length < 2) return null;

      const range = selection.getRangeAt(0);
      const startElement = nodeElement(range.startContainer);
      const endElement = nodeElement(range.endContainer);
      const note = startElement?.closest?.('.note');
      if (!note || !noteRoot.contains(note) || !endElement || !note.contains(endElement)) return null;

      const noteBody = note.querySelector('.note-body');
      const fullText = noteBody?.innerText || note.innerText || '';
      const normalizedFullText = fullText.replace(/\\s+/g, ' ');
      const normalizedSelected = selectedText.replace(/\\s+/g, ' ');
      const start = normalizedFullText.indexOf(normalizedSelected);
      const before = start >= 0 ? normalizedFullText.slice(Math.max(0, start - 700), start) : '';
      const after = start >= 0
        ? normalizedFullText.slice(start + normalizedSelected.length, start + normalizedSelected.length + 700)
        : '';
      const slideNumber = Number(note.dataset.page);
      const page = pages.find(item => Number(item.slideNumber) === slideNumber) || {{}};
      return {{
        deckId,
        slideNumber,
        slideTitle: page.title || `第 ${{slideNumber}} 页`,
        selectedText: clipText(selectedText, 1200),
        contextBefore: clipText(before, 700),
        contextAfter: clipText(after, 700),
      }};
    }}

    function showSelectionToolbar() {{
      const payload = buildSelectionPayload();
      if (!payload) {{
        hideSelectionToolbar();
        return;
      }}
      currentSelectionPayload = payload;
      const selection = window.getSelection();
      const rect = selection.getRangeAt(0).getBoundingClientRect();
      const left = Math.min(Math.max(8, rect.left), Math.max(8, window.innerWidth - 570));
      const top = Math.max(8, rect.top - 52);
      selectionToolbar.style.left = `${{left}}px`;
      selectionToolbar.style.top = `${{top}}px`;
      selectionHint.textContent = `第 ${{payload.slideNumber}} 页：${{clipText(payload.selectedText, 42)}}`;
      selectionToolbar.classList.add('show');
    }}

    function hideSelectionToolbar() {{
      currentSelectionPayload = null;
      selectionToolbar.classList.remove('show');
    }}

    function quoteTextForClipboard(payload) {{
      return [
        `引用自第 ${{payload.slideNumber}} 页：${{payload.slideTitle}}`,
        '',
        payload.selectedText,
        '',
        '前文上下文：',
        payload.contextBefore || '无',
        '',
        '后文上下文：',
        payload.contextAfter || '无',
      ].join('\\n');
    }}

    function sendSelectionToBranch() {{
      const payload = currentSelectionPayload || buildSelectionPayload();
      if (!payload) return;
      try {{
        const rootWindow = window.parent || window;
        const url = new URL(rootWindow.location.href);
        url.searchParams.set('intp_action', 'branch_quote');
        url.searchParams.set('deck_id', String(payload.deckId));
        url.searchParams.set('slide_number', String(payload.slideNumber));
        url.searchParams.set('selected_text', payload.selectedText);
        url.searchParams.set('context_before', payload.contextBefore);
        url.searchParams.set('context_after', payload.contextAfter);
        url.hash = 'ppt-branch-question';
        rootWindow.location.href = url.toString();
      }} catch (error) {{
        navigator.clipboard?.writeText(quoteTextForClipboard(payload));
        alert('浏览器阻止了自动引用，已尝试复制引用内容。请粘贴到下方插问框。');
      }}
    }}

    function copyCurrentSelection() {{
      const payload = currentSelectionPayload || buildSelectionPayload();
      if (!payload) return;
      navigator.clipboard?.writeText(quoteTextForClipboard(payload));
      selectionHint.textContent = '引用内容已复制';
      window.setTimeout(showSelectionToolbar, 800);
    }}

    askSelectionButton.addEventListener('mousedown', event => event.preventDefault());
    copySelectionButton.addEventListener('mousedown', event => event.preventDefault());
    askSelectionButton.addEventListener('click', sendSelectionToBranch);
    copySelectionButton.addEventListener('click', copyCurrentSelection);
    noteRoot.addEventListener('mouseup', () => window.setTimeout(showSelectionToolbar, 40));
    noteRoot.addEventListener('keyup', () => window.setTimeout(showSelectionToolbar, 40));
    document.addEventListener('mousedown', (event) => {{
      if (!selectionToolbar.contains(event.target)) {{
        window.setTimeout(() => {{
          const selection = window.getSelection();
          if (!selection || selection.isCollapsed) hideSelectionToolbar();
        }}, 80);
      }}
    }});

    function nearestScrollPanel(target) {{
      const element = target?.closest?.('.pages, .notes');
      if (element) return element;
      return pageRoot;
    }}

    function containedWheelScroll(event) {{
      const panel = nearestScrollPanel(event.target);
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      panel.scrollBy({{ top: event.deltaY, left: event.deltaX, behavior: 'auto' }});
    }}

    window.addEventListener('wheel', containedWheelScroll, {{ capture: true, passive: false }});
    document.addEventListener('wheel', containedWheelScroll, {{ capture: true, passive: false }});
  </script>
</body>
</html>
"""


def _image_data_uri(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    suffix = path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else "png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def _image_exists(slide: dict) -> bool:
    image_path = slide.get("image_path") or ""
    return bool(image_path and Path(image_path).exists())


def _image_paths_for_generation(
    slide: dict,
    send_image_when_no_text: bool,
    *,
    supports_image_input: bool | None = None,
    force_image_input: bool = False,
) -> list[str]:
    if not send_image_when_no_text and not force_image_input:
        return []
    if supports_image_input is None:
        supports_image_input = _active_provider_supports_image_input()
    if not supports_image_input:
        return []
    if not force_image_input and not _is_text_empty(slide):
        return []
    image_path = slide.get("image_path") or ""
    if image_path and Path(image_path).exists():
        return [image_path]
    return []


def _latest_explanation(slide_id: int) -> dict | None:
    user_id = require_login().id
    return fetch_one(
        """
        SELECT *
        FROM slide_explanations
        WHERE user_id = ? AND slide_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, slide_id),
    )


def _latest_explanations_by_slide_ids(slide_ids: list[int]) -> dict[int, dict]:
    if not slide_ids:
        return {}
    user_id = require_login().id
    latest: dict[int, dict] = {}
    chunk_size = 900
    for start in range(0, len(slide_ids), chunk_size):
        chunk = slide_ids[start : start + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = fetch_all(
            f"""
            SELECT id, slide_id, model, explanation, created_at
            FROM (
                SELECT
                    se.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY se.slide_id
                        ORDER BY se.created_at DESC, se.id DESC
                    ) AS rn
                FROM slide_explanations se
                WHERE se.user_id = ? AND se.slide_id IN ({placeholders})
            )
            WHERE rn = 1
            """,
            (user_id, *tuple(chunk)),
        )
        latest.update({int(row["slide_id"]): row for row in rows})
    return latest


def _questions_by_slide_ids(slide_ids: list[int]) -> dict[int, list[dict]]:
    if not slide_ids:
        return {}
    user_id = require_login().id
    grouped: dict[int, list[dict]] = {int(slide_id): [] for slide_id in slide_ids}
    chunk_size = 900
    for start in range(0, len(slide_ids), chunk_size):
        chunk = slide_ids[start : start + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = fetch_all(
            f"""
            SELECT slide_id, question, answer, model, category, status, sort_order, created_at
            FROM slide_questions
            WHERE user_id = ? AND slide_id IN ({placeholders})
            ORDER BY sort_order ASC, created_at ASC, id ASC
            """,
            (user_id, *tuple(chunk)),
        )
        for row in rows:
            grouped.setdefault(int(row["slide_id"]), []).append(
                {
                    "question": row["question"],
                    "answer": row["answer"],
                    "model": row["model"],
                    "category": row["category"],
                    "status": row["status"],
                    "sortOrder": row["sort_order"],
                    "createdAt": row["created_at"],
                }
            )
    return grouped


def _build_slide_prompt(
    deck: dict,
    slide: dict,
    *,
    image_attached: bool = False,
    ignore_extracted_text: bool = False,
) -> str:
    slide_text = "" if ignore_extracted_text else (slide["slide_text"] or "")
    subject = deck.get("subject") or "未分类"
    if ignore_extracted_text and image_attached and _image_exists(slide):
        slide_text = "本次已选择不使用 PPT/PDF 识别文字。我会随请求附上该页原图，请直接根据页面图片内容讲解，尤其注意公式、符号、图表和推导步骤；不要依赖 OCR 文本，也不要编造图片中不存在的信息。"
    elif ignore_extracted_text:
        slide_text = "本次已选择不使用 PPT/PDF 识别文字，但当前请求没有附带页面图片。请提醒我：需要切换支持图片输入的视觉模型，或先生成 / 修复原页面图片。"
    elif not slide_text.strip() and image_attached and _image_exists(slide):
        slide_text = "这一页没有提取到可用文字。我会随请求附上该页原图，请直接根据页面图片内容讲解；不要编造图片中不存在的信息。"
    elif not slide_text.strip() and _image_exists(slide):
        slide_text = "这一页没有提取到可用文字，当前请求没有附带页面图片。请提醒我：需要切换支持图片输入的视觉模型，或先对 PDF 做 OCR 后重新导入。"
    return render_template(
        "ppt_slide_explain.md",
        {
            "subject": subject,
            "deck_title": deck["title"],
            "slide_number": str(slide["slide_number"]),
            "slide_title": slide["title"] or "未命名页面",
            "slide_text": slide_text or "这一页没有解析到文字。",
            "related_knowledge": _related_knowledge_context(subject),
        },
    )


def _related_knowledge_context(subject: str, limit: int = 8) -> str:
    if not subject or subject == "未分类":
        return "暂无同科目知识卡片。"

    cards = fetch_all(
        """
        SELECT id, topic, core_question, one_sentence, mastery
        FROM knowledge_cards
        WHERE subject = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (subject, limit),
    )
    if not cards:
        return "暂无同科目知识卡片。"

    lines = []
    for card in cards:
        topic = card.get("topic") or "未命名知识点"
        question = card.get("core_question") or "暂无核心问题"
        one_sentence = card.get("one_sentence") or "暂无一句话解释"
        mastery = card.get("mastery", 0)
        lines.append(f"- #{card['id']} {topic}（掌握度 {mastery}%）：{question}；{one_sentence}")
    return "\n".join(lines)


def _build_branch_prompt(deck: dict, slide: dict, latest: dict | None, question: str) -> str:
    return render_template(
        "ppt_branch_question.md",
        {
            "subject": deck.get("subject") or "未分类",
            "deck_title": deck["title"],
            "slide_number": str(slide["slide_number"]),
            "slide_title": slide["title"] or "未命名页面",
            "slide_text": slide["slide_text"] or "这一页没有解析到文字。",
            "main_explanation": latest["explanation"] if latest else "尚未生成主线讲解。",
            "question": question,
        },
    )


def _deck_label(decks: dict[int, dict], deck_id: int) -> str:
    deck = decks[deck_id]
    category = deck.get("category") or "未分类"
    status = deck.get("status") or "使用中"
    order = int(deck.get("sort_order") or 0)
    return f"#{deck_id} · {status} · {category} · 排序 {order} · {deck['subject'] or '未分类'} · {deck['title']} · {deck['slide_count']} 页"


def _slide_label(slides: dict[int, dict], slide_id: int) -> str:
    slide = slides[slide_id]
    return f"第 {slide['slide_number']} 页 · {slide['title'] or '未命名页面'}"


def _format_slide_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(f"- {line}" for line in lines)


def _is_pdf_deck(deck: dict) -> bool:
    filename = str(deck.get("filename") or "")
    file_path = str(deck.get("file_path") or "")
    return filename.lower().endswith(".pdf") or file_path.lower().endswith(".pdf")


def _active_api_key() -> str:
    provider_key = st.session_state.get("active_api_provider_key")
    return st.session_state.get(f"api_key_provider_{provider_key}", "")


def _is_text_empty(slide: dict) -> bool:
    return not (slide.get("slide_text") or "").strip()


def _active_provider_supports_image_input() -> bool:
    provider_key = st.session_state.get("active_api_provider_key")
    providers = list_api_providers()
    provider = next((item for item in providers if item["provider_key"] == provider_key), None)
    if not provider:
        return False
    if provider.get("provider_type") != "openai_chat":
        return False

    model = str(st.session_state.get("active_api_model") or provider.get("model") or "").lower()
    text_only_markers = (
        "deepseek",
        "claude",
        "kimi",
        "moonshot",
        "yi-",
        "doubao",
        "ernie",
        "hunyuan",
        "llama",
        "mistral",
    )
    if any(marker in model for marker in text_only_markers):
        return False

    vision_markers = (
        "vision",
        "visual",
        "image",
        "vl",
        "gpt-4o",
        "gpt-4.1",
        "gpt-5",
        "o4",
        "qwen-vl",
        "glm-4v",
    )
    return any(marker in model for marker in vision_markers)


def _is_image_input_error(exc: AIServiceError) -> bool:
    message = str(exc).lower()
    markers = (
        "model_incompatible",
        "support image input",
        "unsupported image",
        "image input",
        "vision",
    )
    return any(marker in message for marker in markers)


def _active_model_label() -> str:
    provider_key = st.session_state.get("active_api_provider_key")
    model = st.session_state.get("active_api_model", DEFAULT_MODEL)
    providers = list_api_providers()
    provider = next((item for item in providers if item["provider_key"] == provider_key), None)
    if not provider:
        return model
    return f"{provider['name']} / {model}"
