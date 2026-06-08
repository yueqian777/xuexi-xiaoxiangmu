from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date
from functools import lru_cache
from pathlib import Path
import time

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from db import BASE_DIR, execute, execute_many, fetch_all, fetch_one, insert_and_get_id
from repositories.ppt_repository import (
    add_slide_explanation,
    add_slide_question,
    close_slide_question,
    flatten_question_subtree,
    get_slide_question_tree,
    latest_explanation,
    latest_explanations_by_slide_ids,
    update_slide_question_status,
    update_slide_question_answer,
    update_slide_bookmark,
    update_slide_learning_metadata,
)
from services.ai_service import (
    AIServiceError,
    DEFAULT_MODEL,
    generate_text,
    is_quota_error,
    list_api_providers,
    list_available_models,
    provider_label,
)
from services import api_parallel_benchmark_service as parallel_benchmark
from services.api_key_ui import render_local_secret_unlock
from services.api_runtime import ensure_active_provider, ensure_provider_model, provider_model_state_key, set_active_provider
from services.auth_service import require_login
from services.knowledge_card_service import knowledge_card_preview_markdown
from services.ppt_context_service import (
    build_lightweight_explanation,
    build_slide_context_map,
    extract_generated_slide_metadata,
    fetch_deck_sections,
    format_pages_for_structure_prompt,
    format_slide_context_package,
    parse_document_structure_response,
    save_deck_structure,
    should_use_lightweight_explanation,
)
from services.ppt_generation_state import apply_stop_request, generation_progress_patch
from services.ppt_service import (
    apply_source_page_to_deck,
    delete_deck_page,
    extract_source_pages,
    import_deck,
    render_missing_page_images,
    save_page_source_file,
)
from services.pdf_extraction_service import MinerUStatus, get_mineru_status, normalize_mineru_math_text
from services.prompt_service import render_template
from services.ppt_reader_state import (
    LAST_READER_DECK_STATE_KEY,
    LAST_READER_POSITION_SETTING_KEY,
    READER_ACTIVE_SLIDE_STATE_PREFIX,
    build_reader_position_payload,
    default_reader_deck_id,
    initial_reader_slide_number,
    parse_reader_position,
    reader_active_slide_number,
    reader_active_slide_state_key,
    reader_image_window_slide_numbers,
    reader_position_setting_key,
    should_refresh_task,
    update_reader_position_state,
)
from services.question_to_knowledge_service import (
    convert_question_to_knowledge,
    ensure_question_review_tasks,
    get_question_knowledge_draft,
    mark_question_understood,
)
from services.study_asset_service import parse_study_assets, save_study_assets

SYNCED_READER_COMPONENT_PATH = BASE_DIR / "components" / "synced_reader"
SYNCED_READER_IMAGE_CACHE_PATH = SYNCED_READER_COMPONENT_PATH / "_reader_image_cache"
SYNCED_READER_IMAGE_URL_BASE = "_reader_image_cache"
SYNCED_READER_COMPONENT = None
READER_IMAGE_WINDOW_RADIUS = 3
READER_IMAGE_PREFETCH_RADIUS = 3
READER_IMAGE_WINDOW_MAX_RADIUS = 8
READER_IMAGE_CACHE_MAX_SLIDES = 15
READER_IMAGE_URL_CACHE_MAX_SLIDES = READER_IMAGE_CACHE_MAX_SLIDES * 2
READER_BACKEND_POSITION_STATE_KEY = "ppt_reader_backend_position_hydrated"
PPT_GENERATION_DEFAULT_PARALLELISM = parallel_benchmark.DEFAULT_PARALLELISM
PPT_PARALLEL_BENCHMARK_MAX_PARALLELISM = parallel_benchmark.DEFAULT_MAX_PARALLELISM
PPT_INLINE_BENCHMARK_MIN_SLIDES = parallel_benchmark.INLINE_BENCHMARK_MIN_SAMPLES
PPT_PARALLEL_BENCHMARK_STATE_KEY = "ppt_parallel_benchmark_results"
PPT_GENERATION_REFRESH_SECONDS = 1.5
PPT_GENERATION_REFRESH_STATE_KEY = "ppt_generation_last_refresh"
PPT_GENERATION_MAX_RETRIES = 3
PPT_STRUCTURE_REFRESH_STATE_KEY = "ppt_structure_last_refresh"
PPT_STUDY_ASSET_REFRESH_STATE_KEY = "ppt_study_asset_last_refresh"
PPT_INTERACTIVE_REQUEST_TIMEOUT_SECONDS = 300
PPT_STUDY_ASSET_REQUEST_TIMEOUT_SECONDS = 300
PPT_STUDY_ASSET_MAX_ATTEMPTS = 3
PPT_STUDY_ASSET_RETRY_DELAY_SECONDS = 2.0


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
        (reader_position_setting_key(user_id),),
    )
    if not row:
        return {}
    return parse_reader_position(row["value"])


def _save_last_reader_position(
    user_id: int,
    deck_id: int,
    slide_number: int | None = None,
    *,
    existing: dict[str, int] | None = None,
) -> None:
    payload = build_reader_position_payload(deck_id, slide_number, existing=existing if existing is not None else _read_last_reader_position(user_id))
    if not payload:
        return

    existing = existing if existing is not None else _read_last_reader_position(user_id)
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
        (reader_position_setting_key(user_id), user_id, json.dumps(payload, ensure_ascii=False)),
    )


def _default_reader_deck_id(deck_ids: list[int], last_position: dict[str, int]) -> int:
    return default_reader_deck_id(deck_ids, last_position, st.session_state.get(LAST_READER_DECK_STATE_KEY))


def _reader_backend_position_signature(last_position: dict[str, int]) -> tuple[int, int]:
    return (
        int(last_position.get("deck_id") or 0),
        int(last_position.get("slide_number") or 0),
    )


def _hydrate_reader_position_from_backend(deck_ids: list[int], last_position: dict[str, int]) -> None:
    signature = _reader_backend_position_signature(last_position)
    if st.session_state.get(READER_BACKEND_POSITION_STATE_KEY) == signature:
        return
    st.session_state[READER_BACKEND_POSITION_STATE_KEY] = signature

    deck_id, slide_number = signature
    if deck_id not in deck_ids:
        return
    st.session_state[LAST_READER_DECK_STATE_KEY] = deck_id
    if slide_number > 0:
        st.session_state[_reader_active_slide_state_key(deck_id)] = slide_number


def _remember_reader_deck_selection(user_id: int, deck_id: int, last_position: dict[str, int]) -> None:
    slide_number = None
    if last_position.get("deck_id") == deck_id:
        slide_number = last_position.get("slide_number")
    _save_last_reader_position(user_id, deck_id, slide_number, existing=last_position)


def _activate_newly_uploaded_deck(deck_id: int, slides: list[dict]) -> None:
    slide_number = int(slides[0]["slide_number"]) if slides else 1
    st.session_state[LAST_READER_DECK_STATE_KEY] = int(deck_id)
    st.session_state[_reader_active_slide_state_key(int(deck_id))] = slide_number
    _save_last_reader_position(require_login().id, int(deck_id), slide_number)


def _initial_reader_slide_number(deck_id: int, slides: list[dict], last_position: dict[str, int]) -> int:
    return initial_reader_slide_number(deck_id, slides, last_position)


def _reader_active_slide_state_key(deck_id: int) -> str:
    return reader_active_slide_state_key(deck_id)


def _reader_active_slide_number(deck_id: int, slides: list[dict], initial_slide_number: int) -> int:
    return reader_active_slide_number(deck_id, slides, initial_slide_number, st.session_state)


def _reader_image_window_slide_numbers(slides: list[dict], active_slide_number: int) -> set[int]:
    return reader_image_window_slide_numbers(slides, active_slide_number, radius=READER_IMAGE_WINDOW_RADIUS)


def _reader_image_cache_state_key(deck_id: int) -> str:
    return f"ppt_reader_image_cache_{int(deck_id)}"


def _reader_valid_slide_numbers(slides: list[dict]) -> set[int]:
    return {int(slide["slide_number"]) for slide in slides}


def _reader_cached_image_slide_numbers(deck_id: int, slides: list[dict]) -> set[int]:
    valid_numbers = _reader_valid_slide_numbers(slides)
    cache = st.session_state.get(_reader_image_cache_state_key(deck_id))
    if not isinstance(cache, dict):
        return set()
    cached: set[int] = set()
    for key in cache:
        try:
            slide_number = int(key)
        except (TypeError, ValueError):
            continue
        if slide_number in valid_numbers:
            cached.add(slide_number)
    return cached


def _coerce_reader_image_radius(value: object, default: int = READER_IMAGE_PREFETCH_RADIUS) -> int:
    try:
        radius = int(value)
    except (TypeError, ValueError):
        radius = default
    return max(0, min(radius, READER_IMAGE_WINDOW_MAX_RADIUS))


def _coerce_reader_image_slide_numbers(values: object, slides: list[dict]) -> set[int]:
    if not isinstance(values, list):
        return set()
    valid_numbers = _reader_valid_slide_numbers(slides)
    selected: set[int] = set()
    for value in values[: READER_IMAGE_CACHE_MAX_SLIDES]:
        try:
            slide_number = int(value)
        except (TypeError, ValueError):
            continue
        if slide_number in valid_numbers:
            selected.add(slide_number)
    return selected


def _remember_reader_image_window(
    deck_id: int,
    slides: list[dict],
    active_slide_number: int,
    *,
    image_window_slide_numbers: object | None = None,
    image_window_radius: object | None = None,
) -> bool:
    if not slides:
        return False
    requested = _coerce_reader_image_slide_numbers(image_window_slide_numbers, slides)
    if requested:
        window_numbers = requested
    else:
        window_numbers = reader_image_window_slide_numbers(
            slides,
            active_slide_number,
            radius=_coerce_reader_image_radius(image_window_radius, READER_IMAGE_WINDOW_RADIUS),
        )
    if not window_numbers:
        return False

    key = _reader_image_cache_state_key(deck_id)
    raw_cache = st.session_state.get(key)
    valid_text_numbers = {str(number) for number in _reader_valid_slide_numbers(slides)}
    cache: dict[str, float] = {}
    if isinstance(raw_cache, dict):
        for raw_key, raw_timestamp in raw_cache.items():
            key_text = str(raw_key)
            if key_text not in valid_text_numbers:
                continue
            try:
                cache[key_text] = float(raw_timestamp)
            except (TypeError, ValueError):
                cache[key_text] = 0.0
    previous = set(cache)
    now = time.monotonic()
    for slide_number in window_numbers:
        cache[str(slide_number)] = now

    if len(cache) > READER_IMAGE_CACHE_MAX_SLIDES:
        protected = {str(number) for number in window_numbers}
        kept = set(protected)
        recent = sorted(
            ((key_text, timestamp) for key_text, timestamp in cache.items() if key_text not in kept),
            key=lambda item: item[1],
            reverse=True,
        )
        for key_text, _ in recent:
            if len(kept) >= READER_IMAGE_CACHE_MAX_SLIDES:
                break
            kept.add(key_text)
        cache = {key_text: cache[key_text] for key_text in kept if key_text in cache}

    st.session_state[key] = cache
    return bool({str(number) for number in window_numbers} - previous)


def render() -> None:
    user = require_login()
    st.title("PPT 逐页讲解")
    st.caption("边看 PPT 边让 GPT 按页讲解；插问单独进入浮窗，不覆盖当前页主线讲解。")

    _resume_interrupted_structure_generation()
    generation_task = _resume_interrupted_generation()
    _render_api_settings(user.id)
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
    _hydrate_reader_position_from_backend(deck_ids, last_position)
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
    sections = fetch_deck_sections(int(deck["id"]), user_id=user.id)

    st.divider()
    _render_deck_actions(deck, slides, latest_by_slide_id, sections, user_id=user.id)
    _render_question_to_knowledge_panel(deck, user_id=user.id)
    _render_synced_reader(deck, slides, latest_by_slide_id, last_position, sections, user_id=user.id)
    _auto_refresh_structure_generation(st.session_state.get("ppt_structure_task"))
    _auto_refresh_running_generation(generation_task)

    st.divider()
    _render_study_asset_generator(deck, sections, slides, latest_by_slide_id)


def _render_api_settings(user_id: int) -> None:
    with st.expander("AI API 设置", expanded=False):
        st.caption("选择任意已启用 Provider。API Key 只保存在当前 Streamlit 会话里，不写入 SQLite。")
        providers = list_api_providers(enabled_only=True, user_id=user_id)
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
        user = require_login()
        deck = fetch_one("SELECT * FROM ppt_decks WHERE user_id = ? AND id = ?", (user.id, deck_id))
        slides = fetch_all(
            "SELECT * FROM ppt_slides WHERE user_id = ? AND deck_id = ? ORDER BY slide_number ASC",
            (user.id, deck_id),
        )
        if deck and slides:
            _activate_newly_uploaded_deck(deck_id, slides)
            _start_document_structure_generation(deck, slides, source="upload")
        st.rerun()


def _render_deck_actions(
    deck: dict,
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
    sections: list[dict],
    *,
    user_id: int,
) -> None:
    st.subheader("整份资料逐页分析")
    missing_images = [slide for slide in slides if not _image_exists(slide)]
    can_render_source = _deck_can_render_page_images(deck)
    cols = st.columns([1.3, 1.3, 2])
    if cols[0].button("生成 / 修复原页面图片", disabled=(not missing_images or not can_render_source)):
        try:
            with st.spinner("正在生成原页面图片..."):
                render_missing_page_images(deck, slides)
            st.success("原页面图片已生成。")
            st.rerun()
        except Exception as exc:
            st.error(f"生成原页面图片失败：{exc}")
    if missing_images and not can_render_source:
        cols[0].caption("导入的公开分享包没有原始 PPT/PDF 时，不能重新渲染原页面图片。")

    _render_source_page_editor(deck, slides)

    _render_document_structure_controls(deck, slides, sections)

    with st.expander("逐页讲解生成配置", expanded=False):
        only_missing = st.checkbox("只生成缺失讲解", value=True)
        input_mode = st.radio(
            "页面内容发送方式",
            ("文字优先，缺文字时发原图", "只用识别文字，不发原图", "直接发原图，不使用识别文字"),
            horizontal=True,
            help="公式、符号或扫描页识别不准时，可选择直接把原页面图片发给支持视觉输入的 API。",
            key=f"ppt_generation_input_mode_{deck['id']}",
        )
        send_image_when_no_text = input_mode != "只用识别文字，不发原图"
        force_image_input = input_mode == "直接发原图，不使用识别文字"
        selected_slides, range_label, force_regenerate = _select_generation_range(slides, sections)
        enabled_providers = list_api_providers(enabled_only=True, user_id=user_id)
        active_provider_key = str(st.session_state.get("active_api_provider_key") or "")
        provider_by_key = {str(provider["provider_key"]): provider for provider in enabled_providers}
        default_provider_keys = [active_provider_key] if active_provider_key in provider_by_key else list(provider_by_key)[:1]
        selected_provider_keys = st.multiselect(
            "本次生成使用的 API 组",
            list(provider_by_key),
            default=default_provider_keys,
            format_func=lambda item_key: provider_label(provider_by_key[item_key]),
            help="可同时选择多个已启用 Provider；后台生成会按各 Provider 的并行上限分配页面。",
            key=f"ppt_generation_provider_group_{deck['id']}",
        )
        provider_pool = _build_generation_provider_pool(
            enabled_providers,
            selected_provider_keys=selected_provider_keys,
            active_provider_key=active_provider_key,
        )
        provider_pool = _apply_parallel_benchmark_results(provider_pool)
        benchmark_cols = st.columns([1.1, 2])
        if benchmark_cols[0].button("测速最大并行路数", disabled=not provider_pool, key=f"ppt_parallel_benchmark_{deck['id']}"):
            if not provider_pool:
                st.warning("请先选择至少一个 API。")
            else:
                with st.spinner("正在测速当前 API 组的最大稳定并行路数..."):
                    benchmark_result = _benchmark_generation_provider_pool(provider_pool)
                _store_parallel_benchmark_results(benchmark_result)
                provider_pool = _apply_parallel_benchmark_results(provider_pool)
                st.success(_format_parallel_benchmark_result(benchmark_result))
        benchmark_summary = _format_parallel_benchmark_summary(provider_pool)
        if benchmark_summary:
            benchmark_cols[1].caption(benchmark_summary)
        benchmark_during_generation = False
        if len(selected_slides) >= PPT_INLINE_BENCHMARK_MIN_SLIDES:
            benchmark_during_generation = st.checkbox(
                "生成时顺带压测当前 API 组",
                value=False,
                help=(
                    f"仅在本次范围不少于 {PPT_INLINE_BENCHMARK_MIN_SLIDES} 页时建议开启；"
                    "如果样本不足或结论不可靠，只记录本地样本，不绑定为最大并行路数。"
                ),
                key=f"ppt_generation_inline_benchmark_{deck['id']}",
            )
        else:
            st.caption(f"生成范围少于 {PPT_INLINE_BENCHMARK_MIN_SLIDES} 页时不建议用生成过程压测，测速结果容易偏低。")
        generation_cols = st.columns([1.3, 1.3, 2])
        adaptive_parallelism = generation_cols[2].checkbox(
            "自适应最快速度",
            value=True,
            help=(
                "自动使用当前 API 组的并行上限；如果触发限流，可关闭后手动调低。\n\n"
                "生成出错的页面会自动重新加入队列，直到本次范围内可生成页面全部成功。\n"
                "左侧滚动到某页时，右侧讲解会自动同步滚动到对应页。"
            ),
            key=f"ppt_generation_adaptive_parallelism_{deck['id']}",
        )
        parallel_cap = _adaptive_generation_parallelism(provider_pool, max(1, len(selected_slides)))
        if adaptive_parallelism:
            parallelism = parallel_cap
            generation_cols[2].caption(f"自适应并行上限：{parallel_cap} 路。")
        else:
            parallelism = generation_cols[2].slider(
                "并行生成路数",
                min_value=1,
                max_value=max(1, parallel_cap),
                value=min(2, max(1, parallel_cap)),
                help="后台生成时同时发起的逐页讲解请求数；遇到限流或上游不稳定时调低。",
                key=f"ppt_generation_parallelism_{deck['id']}",
            )
        group_supports_image_input = any(provider.get("supports_image_input") for provider in provider_pool)
        if force_image_input and not group_supports_image_input:
            st.warning("当前 API 组看起来没有支持图片输入的 Provider。直接发原图模式无法生成；请加入视觉模型后再试。")
        elif send_image_when_no_text and not group_supports_image_input:
            st.warning("当前 API 组看起来没有支持图片输入的 Provider。空白扫描页会被跳过；请加入视觉模型，或重新导入可提取文字的 PDF。")
        st.caption(f"当前生成范围：{range_label}；将逐页调用 API 并保存到右侧讲解区。")
        run_in_background = st.checkbox("后台运行（切换页面时继续生成）", value=True)
        if st.button("生成所选范围逐页讲解", type="primary"):
            if not provider_pool:
                st.error("请至少选择一个已启用 Provider 作为本次生成的 API 组。")
                return
            _generate_whole_deck_explanations(
                deck,
                selected_slides,
                only_missing=only_missing and not force_regenerate,
                send_image_when_no_text=send_image_when_no_text,
                force_image_input=force_image_input,
                supports_image_input=group_supports_image_input,
                latest_by_slide_id=latest_by_slide_id,
                all_slides=slides,
                sections=sections,
                background=run_in_background,
                parallelism=parallelism,
                provider_pool=provider_pool,
                adaptive_parallelism=adaptive_parallelism,
                benchmark_during_generation=benchmark_during_generation,
                user_id=user_id,
            )


def _question_to_knowledge_pending_key(deck_id: int) -> str:
    return f"ppt_question_to_knowledge_pending_{int(deck_id)}"


def _render_question_to_knowledge_panel(deck: dict, *, user_id: int) -> None:
    key = _question_to_knowledge_pending_key(int(deck["id"]))
    pending = st.session_state.get(key)
    if not pending:
        return
    try:
        question_id = int(pending.get("question_id") if isinstance(pending, dict) else pending)
    except (TypeError, ValueError):
        st.session_state.pop(key, None)
        return
    draft = get_question_knowledge_draft(user_id, question_id)
    if not draft:
        with st.expander("Question to knowledge card", expanded=True):
            st.warning("This question is no longer available.")
            if st.button("Dismiss", key=f"dismiss_missing_question_{question_id}"):
                st.session_state.pop(key, None)
                st.rerun()
        return

    existing_card = _question_existing_knowledge_card(user_id, question_id)
    with st.expander("Question to knowledge card", expanded=True):
        st.caption(f"Source question #{question_id}")
        if existing_card:
            st.info(f"Already linked to knowledge card #{existing_card['id']}. Submitting will reuse it.")
        with st.form(f"question_to_knowledge_form_{int(deck['id'])}_{question_id}"):
            subject = st.text_input("Subject", value=str(draft.get("subject") or "Uncategorized"))
            topic = st.text_input("Topic", value=str(draft.get("topic") or "Question"))
            core_question = st.text_area("Core question", value=str(draft.get("core_question") or ""), height=90)
            one_sentence = st.text_area("One sentence", value=str(draft.get("one_sentence") or ""), height=80)
            logic_or_formula = st.text_area("Logic or formula", value=str(draft.get("logic_or_formula") or ""), height=140)
            application = st.text_area("Application", value=str(draft.get("application") or ""), height=110)
            cols = st.columns([1, 1, 2])
            mastery = cols[0].number_input("Mastery", min_value=0, max_value=100, value=int(draft.get("mastery") or 60), step=5)
            need_review = cols[1].checkbox("Add review", value=bool(draft.get("need_review", True)))
            submitted = cols[2].form_submit_button("Save knowledge card", type="primary")
            cancelled = cols[2].form_submit_button("Cancel")
        if cancelled:
            st.session_state.pop(key, None)
            st.rerun()
        if submitted:
            try:
                result = convert_question_to_knowledge(
                    user_id,
                    question_id,
                    overrides={
                        "subject": subject,
                        "topic": topic,
                        "core_question": core_question,
                        "one_sentence": one_sentence,
                        "logic_or_formula": logic_or_formula,
                        "application": application,
                        "mastery": mastery,
                        "need_review": need_review,
                    },
                    create_review_tasks=need_review,
                )
            except Exception as exc:
                st.error(f"Failed to create knowledge card: {exc}")
                return
            st.session_state.pop(key, None)
            verb = "Created" if result.get("created") else "Reused"
            st.success(f"{verb} knowledge card #{result['knowledge_id']}.")
            st.rerun()


def _question_existing_knowledge_card(user_id: int, question_id: int) -> dict | None:
    return fetch_one(
        """
        SELECT id, topic
        FROM knowledge_cards
        WHERE user_id = ? AND source_question_id = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(user_id), int(question_id)),
    )


def _render_source_page_editor(deck: dict, slides: list[dict]) -> None:
    if not slides:
        return

    deck_id = int(deck["id"])
    slide_numbers = [int(slide["slide_number"]) for slide in slides]
    max_slide_number = max(slide_numbers)
    source_state_key = f"ppt_source_page_editor_{deck_id}"
    mode_key = f"ppt_source_page_editor_mode_{deck_id}"

    with st.expander("从另一个 PPT / PDF 插入、替换或删除单页", expanded=False):
        operation = st.radio(
            "页面操作",
            ("插入到目标页前", "替换目标页", "删除当前已有页面"),
            horizontal=True,
            key=mode_key,
        )

        if operation == "删除当前已有页面":
            st.caption("删除会移除该页讲解和查问，后面的页码自动前移。")
            target_slide_number = st.selectbox(
                "目标页",
                slide_numbers,
                format_func=lambda value: f"删除第 {value} 页",
                key=f"ppt_delete_target_slide_{deck_id}",
            )
            confirmed = st.checkbox(
                "确认删除这一页及其讲解和查问",
                key=f"ppt_delete_target_confirm_{deck_id}",
            )
            if st.button(
                "应用到当前资料",
                type="primary",
                disabled=not confirmed,
                key=f"ppt_delete_target_apply_{deck_id}",
            ):
                try:
                    with st.spinner("正在删除页面并调整后续页码..."):
                        delete_deck_page(deck, target_slide_number=int(target_slide_number))
                    next_slide_number = min(int(target_slide_number), max(1, max_slide_number - 1))
                    update_reader_position_state(st.session_state, deck_id=deck_id, slide_number=next_slide_number)
                    st.success(f"已删除第 {target_slide_number} 页，后续页码已前移。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"删除页面失败：{exc}")
            return

        st.caption("不会删除已有讲解和查问；替换只换页面内容。")
        uploaded = st.file_uploader(
            "选择包含目标页面的 PPTX 或 PDF 文件",
            type=["pptx", "pdf"],
            key=f"ppt_source_page_file_{deck_id}",
        )
        source_method = "local"
        if uploaded is not None and Path(getattr(uploaded, "name", "")).suffix.lower() == ".pdf":
            mineru_status = get_mineru_status()
            method_key = f"ppt_source_pdf_extraction_method_{deck_id}"
            extraction_options = _pdf_extraction_method_options(mineru_status)
            option_labels = dict(extraction_options)
            option_values = [value for value, _label in extraction_options]
            if st.session_state.get(method_key) not in option_values:
                st.session_state[method_key] = "local"
            source_method = st.radio(
                "来源 PDF 提取方式",
                option_values,
                format_func=lambda value: option_labels[value],
                key=method_key,
                help="只用于解析本次上传的来源 PDF，不会自动覆盖当前资料页面。",
            )
            st.caption(mineru_status.message)
            if not mineru_status.available:
                st.caption("MinerU 是自愿安装的辅助配置，不会随 requirements.txt 自动安装。")

        if st.button(
            "解析来源文件",
            disabled=uploaded is None,
            key=f"ppt_source_page_parse_{deck_id}",
        ):
            try:
                with st.spinner("正在解析来源文件页面..."):
                    saved_path = save_page_source_file(uploaded)
                    source_pages = extract_source_pages(saved_path, method=source_method)
                if not source_pages:
                    st.warning("这个来源文件没有解析到可用页面。")
                else:
                    st.session_state[source_state_key] = {
                        "name": getattr(uploaded, "name", saved_path.name),
                        "path": str(saved_path),
                        "pages": source_pages,
                    }
                    st.success(f"已解析 {len(source_pages)} 页来源页面。")
            except Exception as exc:
                st.error(f"解析来源文件失败：{exc}")

        source_state = st.session_state.get(source_state_key)
        if not isinstance(source_state, dict) or not source_state.get("pages"):
            return

        source_pages = list(source_state.get("pages") or [])
        page_by_number = {int(page["slide_number"]): page for page in source_pages}
        source_numbers = sorted(page_by_number)
        st.caption(f"当前来源：{source_state.get('name') or Path(str(source_state.get('path') or '')).name}")
        source_slide_number = st.selectbox(
            "来源页",
            source_numbers,
            format_func=lambda value: _source_page_label(page_by_number[int(value)]),
            key=f"ppt_source_page_number_{deck_id}",
        )
        source_page = page_by_number[int(source_slide_number)]
        preview_path = Path(str(source_page.get("image_path") or ""))
        if preview_path.exists() and preview_path.is_file():
            st.image(str(preview_path), caption=f"来源第 {source_slide_number} 页", use_container_width=True)

        if operation == "插入到目标页前":
            target_options = list(range(1, max_slide_number + 2))
            target_slide_number = st.selectbox(
                "目标位置",
                target_options,
                format_func=lambda value: f"追加到末尾（第 {value} 页）" if int(value) == max_slide_number + 1 else f"插入到第 {value} 页前",
                key=f"ppt_source_insert_target_{deck_id}",
            )
            mode = "insert"
        else:
            target_slide_number = st.selectbox(
                "目标位置",
                slide_numbers,
                format_func=lambda value: f"替换第 {value} 页",
                key=f"ppt_source_replace_target_{deck_id}",
            )
            mode = "replace"

        if st.button("应用到当前资料", type="primary", key=f"ppt_source_page_apply_{deck_id}"):
            try:
                with st.spinner("正在应用页面变更..."):
                    apply_source_page_to_deck(
                        deck,
                        source_page,
                        target_slide_number=int(target_slide_number),
                        mode=mode,
                    )
                update_reader_position_state(st.session_state, deck_id=deck_id, slide_number=int(target_slide_number))
                if mode == "insert":
                    st.success(f"已把来源第 {source_slide_number} 页插入到当前第 {target_slide_number} 页位置。")
                else:
                    st.success(f"已用来源第 {source_slide_number} 页替换当前第 {target_slide_number} 页。")
                st.rerun()
            except Exception as exc:
                st.error(f"应用页面变更失败：{exc}")


def _source_page_label(page: dict) -> str:
    slide_number = int(page.get("slide_number") or 0)
    title = str(page.get("title") or "未命名页面").strip() or "未命名页面"
    text = str(page.get("slide_text") or "").strip().replace("\n", " ")
    suffix = f" · {text[:40]}" if text else ""
    return f"第 {slide_number} 页 · {title[:40]}{suffix}"


def _render_document_structure_controls(deck: dict, slides: list[dict], sections: list[dict]) -> None:
    generated_at = deck.get("outline_generated_at") or ""
    with st.expander("AI 文档目录与分块", expanded=not bool(sections)):
        if sections:
            st.caption(
                f"已生成 {len(sections)} 个目录块。"
                + (f" 最近更新时间：{generated_at}" if generated_at else "")
            )
            st.caption("当前目录整理生成块级标题、摘要和上下文，用于后续按目录块逐页讲解。")
            outline = (deck.get("outline") or "").strip()
            if outline:
                st.markdown("**文档大纲**")
                st.write(outline)
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "目录块": f"{section['section_index']}. {section['title']}",
                            "页码": f"{section['start_slide']}-{section['end_slide']}",
                            "核心问题": section.get("core_question") or "",
                            "摘要": section.get("summary") or "",
                        }
                        for section in sections
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("还没有 AI 文档目录分块。建议先生成分块，再按目录块生成逐页讲解。")

        if st.button("生成 / 更新文档目录分块", key=f"ppt_structure_generate_{deck['id']}"):
            try:
                with st.spinner("正在启动后台目录分块任务..."):
                    _start_document_structure_generation(deck, slides, source="manual")
            except Exception as exc:
                st.error(f"生成文档目录分块失败：{exc}")


def _start_document_structure_generation(deck: dict, slides: list[dict], *, source: str = "manual") -> None:
    existing = st.session_state.get("ppt_structure_task")
    if existing and existing.get("status") == "running":
        st.info("AI 文档目录分块正在后台生成，不会重复启动。")
        st.rerun()
        return

    task = {
        "status": "running",
        "progress": 0.03,
        "status_text": "正在后台整理文档目录分块...",
        "deck_id": int(deck["id"]),
        "source": source,
        "provider_key": st.session_state.get("active_api_provider_key"),
        "api_key": _active_api_key(),
        "active_model": st.session_state.get("active_api_model", DEFAULT_MODEL),
        "max_tokens": int(st.session_state.get("active_api_max_tokens", 4096)),
        "reasoning_depth": st.session_state.get("active_api_reasoning_depth"),
        "user_id": int(deck["user_id"]) if deck.get("user_id") is not None else require_login().id,
        "sections": 0,
        "stop_requested": False,
    }
    st.session_state["ppt_structure_task"] = task
    thread = threading.Thread(
        target=_background_document_structure_worker,
        args=(task, deck, slides),
        daemon=True,
    )
    thread.start()
    st.success("已开始后台生成 AI 文档目录分块；切换页面后会继续执行。")
    st.rerun()


def _resume_interrupted_structure_generation() -> None:
    task = st.session_state.get("ppt_structure_task")
    if not task:
        return

    status = apply_stop_request(task, default_status_text="文档目录分块已停止")

    if status == "completed":
        task["_post_render_refreshed_status"] = status
        st.success(f"AI 文档目录分块完成：{task.get('sections', 0)} 个目录块。")
        return
    if status == "failed":
        task["_post_render_refreshed_status"] = status
        st.error(f"AI 文档目录分块失败：{task.get('error') or task.get('status_text') or '未知错误'}")
        return
    if status == "stopped":
        task["_post_render_refreshed_status"] = status
        st.warning(f"AI 文档目录分块已停止：{task.get('status_text', '已中断')}")
        return
    if status != "running":
        return

    col1, col2 = st.columns([1, 0.15])
    with col1:
        st.info("AI 文档目录分块正在后台进行...")
        st.progress(float(task.get("progress") or 0.05), text=task.get("status_text", "正在整理目录分块..."))
    with col2:
        if st.button("停止", key="stop_structure_generation"):
            task["stop_requested"] = True
            st.rerun()
            return

    if not _should_refresh_task(task, PPT_STRUCTURE_REFRESH_STATE_KEY, interval=1.5):
        return
    time.sleep(0.5)
    st.rerun()


def _background_document_structure_worker(task: dict, deck: dict, slides: list[dict]) -> None:
    try:
        if task.get("stop_requested"):
            task["status"] = "stopped"
            task["status_text"] = "文档目录分块已停止"
            return
        task["progress"] = 0.12
        task["status_text"] = "正在读取已提取文本并整理目录块..."
        structure = _generate_document_structure(
            deck,
            slides,
            provider_key=task.get("provider_key"),
            api_key=task.get("api_key"),
            active_model=task.get("active_model") or DEFAULT_MODEL,
            max_tokens=int(task.get("max_tokens") or 4096),
            reasoning_depth=task.get("reasoning_depth"),
            user_id=int(task.get("user_id") or 0) or None,
        )
        if task.get("stop_requested"):
            task["status"] = "stopped"
            task["status_text"] = "文档目录分块已停止"
            return
        task["status"] = "completed"
        task["progress"] = 1.0
        task["sections"] = len(structure.get("sections") or [])
        task["status_text"] = f"目录分块完成：{task['sections']} 个目录块"
    except Exception as exc:
        task["status"] = "failed"
        task["progress"] = 1.0
        task["error"] = str(exc)
        task["status_text"] = f"目录分块失败：{exc}"


def _generate_document_structure(
    deck: dict,
    slides: list[dict],
    *,
    provider_key: str | None = None,
    api_key: str | None = None,
    active_model: str | None = None,
    max_tokens: int | None = None,
    reasoning_depth: str | None = None,
    user_id: int | None = None,
) -> dict:
    deck_user_id = (
        int(user_id)
        if user_id is not None
        else int(deck["user_id"]) if deck.get("user_id") is not None else require_login().id
    )
    per_page_limit = 420
    if len(slides) > 80:
        per_page_limit = 180
    elif len(slides) > 40:
        per_page_limit = 260
    page_list = format_pages_for_structure_prompt(slides, per_page_limit=per_page_limit)
    prompt = render_template(
        "ppt_document_structure.md",
        {
            "subject": deck.get("subject") or "未分类",
            "deck_title": deck.get("title") or "学习资料",
            "slide_count": str(len(slides)),
            "page_list": page_list,
        },
    )
    response = generate_text(
        prompt,
        provider_key=provider_key if provider_key is not None else st.session_state.get("active_api_provider_key"),
        api_key=api_key if api_key is not None else _active_api_key(),
        model_override=active_model or st.session_state.get("active_api_model", DEFAULT_MODEL),
        max_output_tokens=min(max(2048, int(max_tokens or st.session_state.get("active_api_max_tokens", 4096))), 4096),
        reasoning_depth=reasoning_depth if reasoning_depth is not None else st.session_state.get("active_api_reasoning_depth"),
        user_id=deck_user_id,
    )
    structure = parse_document_structure_response(response, slides)
    save_deck_structure(int(deck["id"]), structure, user_id=deck_user_id)
    return structure


def _render_synced_reader(
    deck: dict,
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
    last_position: dict[str, int],
    sections: list[dict],
    *,
    user_id: int | None = None,
) -> None:
    st.subheader("同步阅读器")
    st.caption("提示：右侧固定插问栏会绑定当前页。你可以直接提问，或选中讲解文字后引用到插问。")
    user_id = int(user_id) if user_id is not None else int(deck.get("user_id") or require_login().id)
    initial_slide_number = _initial_reader_slide_number(int(deck["id"]), slides, last_position)
    active_state_key = _reader_active_slide_state_key(int(deck["id"]))
    active_slide_number = initial_slide_number
    st.session_state[active_state_key] = active_slide_number
    _remember_reader_image_window(int(deck["id"]), slides, active_slide_number)
    image_slide_numbers = _reader_cached_image_slide_numbers(int(deck["id"]), slides)
    active_slide_ids = [
        int(slide["id"])
        for slide in slides
        if int(slide["slide_number"]) in image_slide_numbers
    ]
    question_by_slide_id = _questions_by_slide_ids(active_slide_ids)
    payload = _build_reader_payload(
        slides,
        latest_by_slide_id,
        question_by_slide_id,
        image_slide_numbers=image_slide_numbers,
    )
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
        active_model=_active_model_label(user_id=user_id),
        pages=payload,
        sections=_reader_sections_payload(sections),
        initial_slide_number=active_slide_number,
        height=850,
        default=None,
        key=f"synced_reader_{deck['id']}",
    )
    if isinstance(component_payload, dict):
        _handle_synced_reader_action(deck, slides, latest_by_slide_id, component_payload, sections, user_id=user_id)


def _handle_synced_reader_action(
    deck: dict,
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
    payload: dict,
    sections: list[dict],
    *,
    user_id: int | None = None,
) -> None:
    user_id = int(user_id) if user_id is not None else int(deck.get("user_id") or require_login().id)
    action = payload.get("action")
    if action not in {
        "canvas_question",
        "save_explanation_edit",
        "save_question_answer_edit",
        "merge_question_thread",
        "close_slide_question",
        "update_slide_question_status",
        "toggle_slide_bookmark",
        "rename_slide_bookmark",
        "reader_position",
    }:
        return
    try:
        query_deck_id = int(payload.get("deckId", 0))
        slide_number = int(payload.get("slideNumber", 0))
    except (TypeError, ValueError):
        return
    if query_deck_id != int(deck["id"]):
        return

    slide = next((item for item in slides if int(item["slide_number"]) == slide_number), None)
    if not slide:
        return

    token = str(payload.get("token") or "").strip()
    if action == "reader_position":
        if _handle_reader_position_update(
            deck,
            slide_number,
            token,
            slides=slides,
            image_window_slide_numbers=payload.get("imageWindowSlideNumbers"),
            image_window_radius=payload.get("imageWindowRadius"),
            user_id=user_id,
        ):
            st.rerun()
        return

    if action == "close_slide_question":
        last_close_token_key = f"ppt_question_close_last_token_{deck['id']}"
        if token and st.session_state.get(last_close_token_key) == token:
            return
        try:
            question_id = int(payload.get("questionId", 0))
        except (TypeError, ValueError):
            return
        if not question_id:
            return
        close_slide_question(question_id, user_id)
        st.session_state.pop(f"ppt_active_question_id_{deck['id']}", None)
        st.session_state.pop(f"ppt_parent_question_id_{deck['id']}", None)
        if token:
            st.session_state[last_close_token_key] = token
        st.toast("插问已关闭，并保留在插问树中。")
        st.rerun()
        return

    if action == "update_slide_question_status":
        last_status_token_key = f"ppt_question_status_last_token_{deck['id']}"
        if token and st.session_state.get(last_status_token_key) == token:
            return
        try:
            question_id = int(payload.get("questionId", 0))
        except (TypeError, ValueError):
            return
        status = str(payload.get("status") or "").strip()
        if not question_id or not status:
            return
        if status == "understood":
            mark_question_understood(user_id, question_id)
            toast_text = "Question marked understood."
        elif status == "review":
            result = ensure_question_review_tasks(user_id, question_id)
            toast_text = f"Review tasks ready for knowledge card #{result['knowledge_id']}."
        elif status == "knowledge_card":
            st.session_state[_question_to_knowledge_pending_key(int(deck["id"]))] = {"question_id": question_id}
            toast_text = "Knowledge card draft is ready."
        else:
            update_slide_question_status(question_id, user_id, status)
            toast_text = "Question status updated."
        if token:
            st.session_state[last_status_token_key] = token
        st.toast(toast_text)
        st.rerun()
        return

    if action in {"toggle_slide_bookmark", "rename_slide_bookmark"}:
        last_bookmark_token_key = f"ppt_slide_bookmark_last_token_{deck['id']}"
        if token and st.session_state.get(last_bookmark_token_key) == token:
            return
        if action == "toggle_slide_bookmark":
            update_slide_bookmark(user_id, int(slide["id"]), enabled=bool(payload.get("enabled")))
        else:
            title = str(payload.get("title") or "").strip()
            update_slide_bookmark(user_id, int(slide["id"]), enabled=True, title=title)
        if token:
            st.session_state[last_bookmark_token_key] = token
        st.toast(f"第 {slide['slide_number']} 页书签已更新。")
        return

    if action == "save_explanation_edit":
        last_edit_token_key = f"ppt_explanation_edit_last_token_{deck['id']}"
        if token and st.session_state.get(last_edit_token_key) == token:
            return
        explanation = str(payload.get("explanation") or "").strip()
        if not explanation:
            st.warning("讲解内容不能为空，未保存本次修改。")
            return
        _save_manual_explanation(int(slide["id"]), explanation, user_id=user_id)
        if token:
            st.session_state[last_edit_token_key] = token
        st.toast(f"第 {slide['slide_number']} 页讲解已保存。")
        return

    if action == "save_question_answer_edit":
        last_answer_edit_token_key = f"ppt_question_answer_edit_last_token_{deck['id']}"
        if token and st.session_state.get(last_answer_edit_token_key) == token:
            return
        try:
            question_id = int(payload.get("questionId", 0))
        except (TypeError, ValueError):
            return
        answer = str(payload.get("answer") or "").strip()
        if not question_id or not answer:
            return
        update_slide_question_answer(user_id, question_id, answer)
        if token:
            st.session_state[last_answer_edit_token_key] = token
        st.toast("插问回答高亮已保存。")
        return

    if action == "merge_question_thread":
        last_merge_token_key = f"ppt_question_merge_last_token_{deck['id']}"
        if token and st.session_state.get(last_merge_token_key) == token:
            return
        try:
            question_id = int(payload.get("questionId", 0))
        except (TypeError, ValueError):
            return
        if question_id:
            flatten_question_subtree(user_id, question_id)
        if token:
            st.session_state[last_merge_token_key] = token
        st.rerun()
        return

    last_token_key = f"ppt_canvas_question_last_token_{deck['id']}"
    if token and st.session_state.get(last_token_key) == token:
        return

    question = str(payload.get("question") or "").strip()
    if not question:
        return

    quote_payload = payload.get("quote") if isinstance(payload.get("quote"), dict) else None
    quote = _quote_from_component_payload(deck, slide, quote_payload) if quote_payload else None
    target_payload = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    parent_question_id = _optional_positive_int(
        payload.get("parentQuestionId") or target_payload.get("parentQuestionId")
    )
    quote_source = str((quote_payload or {}).get("sourceKind") or (quote_payload or {}).get("sourceType") or "slide")
    quote_source_question_id = _optional_positive_int(
        (quote_payload or {}).get("questionId")
        or (quote_payload or {}).get("sourceQuestionId")
        or parent_question_id
    )
    full_question = _compose_quoted_branch_question(quote, question) if quote else question
    context_by_slide = build_slide_context_map(deck, slides, sections)
    prompt = _build_branch_prompt(
        deck,
        slide,
        latest_by_slide_id.get(int(slide["id"])),
        full_question,
        context=context_by_slide.get(int(slide["slide_number"])),
    )
    try:
        with st.spinner(f"正在回答第 {slide_number} 页插问..."):
            answer = generate_text(
                prompt,
                provider_key=st.session_state.get("active_api_provider_key"),
                api_key=_active_api_key(),
                model_override=st.session_state.get("active_api_model", DEFAULT_MODEL),
                max_output_tokens=int(st.session_state.get("active_api_max_tokens", 4096)),
                request_timeout=PPT_INTERACTIVE_REQUEST_TIMEOUT_SECONDS,
                user_id=user_id,
            )
        add_slide_question(
            user_id,
            slide["id"],
            question,
            answer,
            _active_model_label(user_id=user_id),
            quote_text=quote["selected_text"] if quote else "",
            parent_question_id=parent_question_id,
            quote_source=quote_source,
            quote_source_question_id=quote_source_question_id,
        )
        update_reader_position_state(
            st.session_state,
            deck_id=int(deck["id"]),
            slide_number=slide_number,
        )
    except AIServiceError as exc:
        st.error(str(exc))
        st.caption("侧边插问调用失败，当前阅读位置不会被修改。")
        return
    except ValueError as exc:
        st.error(f"插问保存失败：{exc}")
        st.caption("请关闭过深或已失效的子插问栏后再试。")
        return

    if token:
        st.session_state[last_token_key] = token
    st.rerun()


def _save_manual_explanation(slide_id: int, explanation: str, *, user_id: int | None = None) -> int:
    user_id = int(user_id) if user_id is not None else require_login().id
    return add_slide_explanation(user_id, int(slide_id), f"手动编辑 / {_active_model_label(user_id=user_id)}", explanation)


def _optional_positive_int(value: object) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _handle_reader_position_update(
    deck: dict,
    slide_number: int,
    token: str = "",
    *,
    slides: list[dict] | None = None,
    image_window_slide_numbers: object | None = None,
    image_window_radius: object | None = None,
    user_id: int | None = None,
) -> bool:
    user_id = int(user_id) if user_id is not None else require_login().id
    deck_id = int(deck["id"])
    last_position_token_key = f"ppt_reader_position_last_token_{deck_id}"
    if token and st.session_state.get(last_position_token_key) == token:
        return False
    changed = update_reader_position_state(
        st.session_state,
        deck_id=deck_id,
        slide_number=int(slide_number),
        token=token,
    )
    image_window_changed = False
    if slides is not None:
        image_window_changed = _remember_reader_image_window(
            deck_id,
            slides,
            int(slide_number),
            image_window_slide_numbers=image_window_slide_numbers,
            image_window_radius=image_window_radius,
        )
    _save_last_reader_position(user_id, deck_id, int(slide_number))
    return changed or image_window_changed


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


def _select_generation_range(slides: list[dict], sections: list[dict]) -> tuple[list[dict], str, bool]:
    modes = ["按目录块生成", "手动选择单页重新生成"]
    if sections:
        modes.append("全部页面按块生成")
    else:
        modes.append("全部页面生成")
        st.warning("当前资料还没有 AI 目录分块；会临时把整份资料作为一个上下文。")
    mode = st.radio(
        "生成范围",
        modes,
        horizontal=True,
        help="按目录块生成会让同一块页面共享块摘要、关键符号、前后页摘要等上下文。",
    )
    slide_by_number = {int(slide["slide_number"]): slide for slide in slides}
    if mode == "按目录块生成" and sections:
        selected_index = st.selectbox(
            "选择目录块",
            [int(section["section_index"]) for section in sections],
            format_func=lambda index: _section_label(sections, index),
        )
        section = next(item for item in sections if int(item["section_index"]) == int(selected_index))
        selected = [
            slide
            for slide in slides
            if int(section["start_slide"]) <= int(slide["slide_number"]) <= int(section["end_slide"])
        ]
        return selected, _section_label(sections, int(selected_index)), False

    if mode == "按目录块生成":
        return slides, f"全部 {len(slides)} 页（未分块）", False

    if mode == "手动选择单页重新生成":
        slide_number = st.selectbox(
            "选择要重新生成的页",
            list(slide_by_number),
            format_func=lambda number: _slide_regeneration_label(number, sections),
        )
        slide = slide_by_number[int(slide_number)]
        return [slide], f"第 {slide_number} 页（强制重新生成）", True

    return slides, f"全部 {len(slides)} 页", False


def _section_label(sections: list[dict], section_index: int) -> str:
    section = next(item for item in sections if int(item["section_index"]) == int(section_index))
    return (
        f"{section['section_index']}. {section['title']} "
        f"（第 {section['start_slide']}-{section['end_slide']} 页）"
    )


def _slide_regeneration_label(slide_number: int, sections: list[dict]) -> str:
    section = next(
        (
            item
            for item in sections
            if int(item["start_slide"]) <= int(slide_number) <= int(item["end_slide"])
        ),
        None,
    )
    if not section:
        return f"第 {slide_number} 页"
    return f"第 {slide_number} 页 · {section.get('title') or '未命名目录块'}"


def _build_slide_groups(slides: list[dict], group_size: int) -> list[list[dict]]:
    return [slides[index : index + group_size] for index in range(0, len(slides), group_size)]


def _group_label(group: list[dict]) -> str:
    if not group:
        return "空批次"
    start = group[0]["slide_number"]
    end = group[-1]["slide_number"]
    return f"第 {start}-{end} 页（共 {len(group)} 页）"


def _render_study_asset_generator(
    deck: dict,
    sections: list[dict],
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
) -> None:
    with st.expander("学习沉淀：从今日阅读内容生成学习登记和知识卡片", expanded=False):
        _render_study_asset_generator_inner(deck, sections, slides, latest_by_slide_id)


def _render_study_asset_generator_inner(
    deck: dict,
    sections: list[dict],
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
) -> None:
    st.caption("根据当前资料的目录块、手动选择的今日学习页码范围和已生成讲解，调用当前 API 生成草稿；确认后写入学习登记、知识点卡片和 1-3-7-14 复习计划。")

    user = require_login()
    slides_with_explanations = _slides_with_latest_explanations(slides, latest_by_slide_id)
    recognized = [slide for slide in slides_with_explanations if _slide_has_learning_content(slide)]
    today_slides = [slide for slide in recognized if _is_today(slide.get("explanation_created_at"))]
    if not recognized:
        st.info("当前资料还没有可沉淀的文字或讲解。请先重新提取 PDF 文字，或生成逐页讲解。")
        return

    completed_slide_numbers = _completed_study_asset_slide_numbers(user.id, int(deck["id"]))
    selected_slides, range_label, scope_mode = _select_study_asset_scope(
        deck,
        recognized,
        sections,
        today_slides,
        completed_slide_numbers=completed_slide_numbers,
    )

    cols = st.columns([1, 1])
    max_chars = cols[1].number_input(
        "最大输入字符",
        min_value=8000,
        max_value=60000,
        value=24000,
        step=2000,
        key=f"asset_max_chars_{deck['id']}",
        help="太长的 PPT 会超过模型上下文，建议先手动缩小今日学习页码范围，或选择单个目录块。",
    )
    include_ai_explanation = cols[0].checkbox(
        "包含 AI 讲解",
        value=True,
        key=f"asset_include_ai_{deck['id']}",
        help="勾选后会把逐页讲解也作为沉淀依据；如果讲解质量不稳定，可以只用 PPT/PDF 识别文字。",
    )

    split_by_sections = scope_mode == "全部目录块" and bool(sections)
    batches = _build_study_asset_batches(
        selected_slides,
        sections=sections,
        max_chars=int(max_chars),
        include_ai_explanation=include_ai_explanation,
        split_by_sections=split_by_sections,
        fallback_range_label=range_label,
    )
    total_used_pages = sum(int(batch["used_pages"]) for batch in batches)
    truncated_count = sum(1 for batch in batches if batch["truncated"])
    st.caption(
        f"将用于生成：{range_label}；分 {len(batches)} 批；实际纳入 {total_used_pages} 页。"
        + (f" {truncated_count} 批内容过长，已按批截断。" if truncated_count else "")
    )
    if split_by_sections:
        st.info("已启用逐目录块生成：每个目录块会单独调用 API，再合并成一个学习登记和知识卡片草稿，减少长课件漏掉后半部分内容。")

    draft_key = f"study_asset_draft_{deck['id']}"
    raw_key = f"study_asset_raw_{deck['id']}"
    meta_key = f"study_asset_meta_{deck['id']}"
    task_key = f"study_asset_task_{deck['id']}"

    task = st.session_state.get(task_key)
    _render_study_asset_task_status(task, task_key, draft_key, raw_key, meta_key)
    is_running = bool(task and task.get("status") == "running")

    if st.button("调用 API 生成学习登记 / 知识卡片草稿", type="primary", key=f"generate_assets_{deck['id']}"):
        usable_batches = [batch for batch in batches if str(batch["reading_content"]).strip()]
        if not usable_batches:
            st.error("没有可发送给 API 的阅读内容。")
            return
        if is_running:
            st.info("学习沉淀草稿正在后台生成，不会重复启动。")
            return
        st.session_state.pop(draft_key, None)
        st.session_state.pop(raw_key, None)
        st.session_state.pop(meta_key, None)
        _start_study_asset_generation_task(
            task_key,
            deck=deck,
            batches=usable_batches,
            all_batches=batches,
            range_label=range_label,
            total_used_pages=total_used_pages,
        )

    draft = st.session_state.get(draft_key)
    if not draft:
        return

    with st.expander("预览将写入的学习登记和知识卡片", expanded=True):
        draft_meta = st.session_state.get(meta_key) or {}
        if draft_meta:
            st.caption(f"当前草稿来源：{draft_meta.get('range_label')}；纳入 {draft_meta.get('used_pages')} 页。")
            if draft_meta.get("range_label") != range_label:
                st.warning("你已经调整了登记范围，但当前预览仍是上一次生成的草稿；需要重新调用 API 才会使用新范围。")
            coverage_report = draft_meta.get("coverage_report") or []
            if coverage_report:
                st.markdown("**覆盖率检查**")
                st.dataframe(pd.DataFrame(coverage_report), use_container_width=True, hide_index=True)
        _render_study_asset_draft_preview(draft)
        with st.expander("查看原始 JSON", expanded=False):
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
            draft_slide_numbers = draft_meta.get("slide_numbers") or _study_asset_slide_numbers(selected_slides)
            _record_completed_study_asset_pages(
                user_id=user.id,
                deck_id=int(deck["id"]),
                slide_numbers=draft_slide_numbers,
                session_id=session_id,
                knowledge_count=len(knowledge_ids),
                range_label=str(draft_meta.get("range_label") or range_label),
            )
            st.success(f"已写入学习记录 #{session_id}，知识点卡片 {len(knowledge_ids)} 张，并已生成复习计划。")
            del st.session_state[draft_key]
            st.session_state.pop(meta_key, None)
            st.rerun()
        if cols[1].button("清除草稿", key=f"clear_assets_{deck['id']}"):
            del st.session_state[draft_key]
            st.session_state.pop(raw_key, None)
            st.session_state.pop(meta_key, None)
            st.session_state.pop(task_key, None)
            st.rerun()


def _render_study_asset_draft_preview(draft: dict) -> None:
    session = draft.get("study_session") or {}
    cards = draft.get("knowledge_cards") or []
    if session:
        st.markdown("**学习登记预览**")
        st.markdown(
            "\n\n".join(
                [
                    f"### {session.get('title') or '未命名学习主题'}",
                    f"**主线问题**\n\n{session.get('main_question') or '待补充'}",
                    f"**总结**\n\n{session.get('summary') or '待补充'}",
                    f"**卡点 / 待追问**\n\n{session.get('blockers') or '暂无'}",
                ]
            )
        )
    if not cards:
        return

    st.markdown("**知识卡片预览**")
    for index, card in enumerate(cards, start=1):
        with st.container(border=True):
            st.caption(f"卡片 {index}")
            st.markdown(knowledge_card_preview_markdown(card))


def _start_study_asset_generation_task(
    task_key: str,
    *,
    deck: dict,
    batches: list[dict],
    all_batches: list[dict],
    range_label: str,
    total_used_pages: int,
) -> None:
    task = {
        "status": "running",
        "progress": 0.0,
        "status_text": "正在后台生成学习沉淀草稿...",
        "deck_id": int(deck["id"]),
        "range_label": range_label,
        "used_pages": int(total_used_pages),
        "slide_numbers": _study_asset_batch_slide_numbers(batches),
        "batch_count": len(batches),
        "completed_batches": 0,
        "batches": batches,
        "all_batches": all_batches,
        "provider_key": st.session_state.get("active_api_provider_key"),
        "api_key": _active_api_key(),
        "active_model": st.session_state.get("active_api_model", DEFAULT_MODEL),
        "max_tokens": int(st.session_state.get("active_api_max_tokens", 4096)),
        "reasoning_depth": st.session_state.get("active_api_reasoning_depth"),
        "user_id": int(deck["user_id"]) if deck.get("user_id") is not None else require_login().id,
        "raw_outputs": [],
        "retried": 0,
        "stop_requested": False,
    }
    st.session_state[task_key] = task
    thread = threading.Thread(
        target=_background_study_asset_worker,
        args=(task, deck),
        daemon=True,
    )
    thread.start()
    st.success("已开始后台生成学习沉淀草稿；切换页面后会继续执行。")
    st.rerun()


def _render_study_asset_task_status(
    task: dict | None,
    task_key: str,
    draft_key: str,
    raw_key: str,
    meta_key: str,
) -> None:
    if not task:
        return

    status = str(task.get("status") or "")
    if status == "completed":
        if task.get("draft") and not task.get("_adopted"):
            st.session_state[draft_key] = task["draft"]
            st.session_state[raw_key] = task.get("raw_outputs") or []
            st.session_state[meta_key] = task.get("meta") or {}
            task["_adopted"] = True
        st.success("后台学习沉淀草稿已生成，请在下方预览后写入数据库。")
        return
    if status == "failed":
        st.error(f"后台生成学习沉淀草稿失败：{task.get('error') or task.get('status_text') or '未知错误'}")
        raw_outputs = task.get("raw_outputs") or []
        if raw_outputs:
            with st.expander("已完成批次的 API 原始返回", expanded=False):
                st.json(raw_outputs)
        if st.button("清除失败任务", key=f"clear_failed_{task_key}"):
            st.session_state.pop(task_key, None)
            st.rerun()
        return
    if status == "stopped":
        st.warning(f"后台学习沉淀草稿已停止：{task.get('status_text', '已中断')}")
        if st.button("清除已停止任务", key=f"clear_stopped_{task_key}"):
            st.session_state.pop(task_key, None)
            st.rerun()
        return
    if status != "running":
        return

    col1, col2 = st.columns([1, 0.15])
    with col1:
        st.info("学习沉淀草稿正在后台生成，可继续阅读或切换页面。")
        st.progress(float(task.get("progress") or 0.0), text=task.get("status_text", "生成中..."))
        retry_text = f"，已重试 {int(task.get('retried') or 0)} 次" if int(task.get("retried") or 0) else ""
        st.caption(f"已完成 {int(task.get('completed_batches') or 0)} / {int(task.get('batch_count') or 0)} 批{retry_text}。")
    with col2:
        if st.button("停止", key=f"stop_{task_key}"):
            task["stop_requested"] = True
            st.rerun()
            return

    refresh_due = _should_refresh_task(task, PPT_STUDY_ASSET_REFRESH_STATE_KEY, interval=1.5)
    # The task can finish while its progress text is unchanged; keep polling so
    # the completed draft is adopted without requiring another user action.
    time.sleep(0.3 if refresh_due else 0.5)
    st.rerun()


def _background_study_asset_worker(task: dict, deck: dict) -> None:
    batch_results = []
    raw_outputs = []
    batches = list(task.get("batches") or [])
    total = len(batches)
    try:
        if not batches:
            raise ValueError("没有可发送给 API 的阅读内容。")

        for index, batch in enumerate(batches, start=1):
            if task.get("stop_requested"):
                task["status"] = "stopped"
                task["status_text"] = "学习沉淀草稿生成已停止"
                return

            task["progress"] = (index - 1) / total
            task["status_text"] = f"正在生成第 {index}/{total} 批：{batch['range_label']}"
            prompt = render_template(
                "ppt_to_study_assets.md",
                {
                    "today": date.today().isoformat(),
                    "subject": deck.get("subject") or "未分类",
                    "deck_title": deck.get("title") or "未命名资料",
                    "range_label": batch["range_label"],
                    "reading_content": batch["reading_content"],
                },
            )
            output = _generate_study_asset_batch_output(task, batch, index, total, prompt)
            raw_outputs.append({"range_label": batch["range_label"], "output": output})
            task["raw_outputs"] = list(raw_outputs)
            assets = parse_study_assets(output)
            batch_results.append({"batch": batch, "assets": assets})
            task["completed_batches"] = index
            task["progress"] = index / total

        if task.get("stop_requested"):
            task["status"] = "stopped"
            task["status_text"] = "学习沉淀草稿生成已停止"
            return

        draft = _merge_study_asset_batches(
            batch_results,
            deck=deck,
            range_label=str(task.get("range_label") or "学习范围"),
        )
        coverage_report = _build_study_asset_coverage_report(
            batch_results,
            list(task.get("all_batches") or batches),
        )
        task["draft"] = draft
        task["meta"] = {
            "range_label": task.get("range_label"),
            "used_pages": int(task.get("used_pages") or 0),
            "slide_numbers": _study_asset_batch_slide_numbers(list(task.get("batches") or [])),
            "batch_count": total,
            "coverage_report": coverage_report,
        }
        task["status"] = "completed"
        task["progress"] = 1.0
        task["status_text"] = f"学习沉淀草稿生成完成：{total} 批"
    except Exception as exc:
        task["status"] = "failed"
        task["progress"] = 1.0
        task["raw_outputs"] = list(raw_outputs)
        task["error"] = str(exc)
        task["status_text"] = f"学习沉淀草稿生成失败：{exc}"


def _generate_study_asset_batch_output(task: dict, batch: dict, index: int, total: int, prompt: str) -> str:
    max_attempts = max(1, int(task.get("max_attempts") or PPT_STUDY_ASSET_MAX_ATTEMPTS))
    for attempt in range(1, max_attempts + 1):
        if task.get("stop_requested"):
            raise AIServiceError("学习沉淀草稿生成已停止")
        try:
            task["status_text"] = f"正在生成第 {index}/{total} 批：{batch['range_label']}"
            if attempt > 1:
                task["status_text"] += f"（第 {attempt}/{max_attempts} 次尝试）"
            return generate_text(
                prompt,
                provider_key=task.get("provider_key"),
                api_key=task.get("api_key"),
                model_override=task.get("active_model") or DEFAULT_MODEL,
                max_output_tokens=int(task.get("max_tokens") or 4096),
                reasoning_depth=task.get("reasoning_depth"),
                request_timeout=PPT_STUDY_ASSET_REQUEST_TIMEOUT_SECONDS,
                user_id=int(task.get("user_id") or 0) or None,
            )
        except AIServiceError as exc:
            category = parallel_benchmark.classify_error_category(exc)
            if category not in {"timeout", "rate_limit"} or attempt >= max_attempts:
                raise
            task["retried"] = int(task.get("retried") or 0) + 1
            task["status_text"] = (
                f"第 {index}/{total} 批：{batch['range_label']} 请求{_study_asset_retry_reason(category)}，"
                f"准备第 {attempt + 1}/{max_attempts} 次尝试。"
            )
            time.sleep(PPT_STUDY_ASSET_RETRY_DELAY_SECONDS)
    raise AIServiceError("学习沉淀草稿生成失败：重试次数已用尽。")


def _study_asset_retry_reason(category: str) -> str:
    if category == "timeout":
        return "超时"
    if category == "rate_limit":
        return "触发频率限制"
    return "失败"


def _slides_with_latest_explanations(slides: list[dict], latest_by_slide_id: dict[int, dict]) -> list[dict]:
    enriched = []
    for slide in slides:
        item = dict(slide)
        latest = latest_by_slide_id.get(int(slide["id"]))
        item["latest_explanation"] = latest["explanation"] if latest else ""
        item["latest_model"] = latest["model"] if latest else ""
        item["explanation_created_at"] = latest["created_at"] if latest else ""
        enriched.append(item)
    return enriched


def _slide_has_learning_content(slide: dict) -> bool:
    return bool((slide.get("slide_text") or "").strip() or (slide.get("latest_explanation") or "").strip())


def _is_today(value: str | None) -> bool:
    return bool(value and value[:10] == date.today().isoformat())


def _study_asset_slide_numbers(slides: list[dict]) -> list[int]:
    numbers: list[int] = []
    seen: set[int] = set()
    for slide in slides:
        try:
            number = int(slide.get("slide_number"))
        except (TypeError, ValueError):
            continue
        if number <= 0 or number in seen:
            continue
        numbers.append(number)
        seen.add(number)
    return numbers


def _study_asset_batch_slide_numbers(batches: list[dict]) -> list[int]:
    numbers: list[int] = []
    seen: set[int] = set()
    for batch in batches:
        for raw_number in batch.get("slide_numbers") or []:
            try:
                number = int(raw_number)
            except (TypeError, ValueError):
                continue
            if number <= 0 or number in seen:
                continue
            numbers.append(number)
            seen.add(number)
    return numbers


def _completed_study_asset_slide_numbers(user_id: int, deck_id: int) -> set[int]:
    rows = fetch_all(
        """
        SELECT DISTINCT slide_number
        FROM ppt_study_asset_pages
        WHERE user_id = ? AND deck_id = ?
        ORDER BY slide_number ASC
        """,
        (int(user_id), int(deck_id)),
    )
    numbers: set[int] = set()
    for row in rows:
        try:
            number = int(row["slide_number"])
        except (TypeError, ValueError, KeyError):
            continue
        if number > 0:
            numbers.add(number)
    return numbers


def _record_completed_study_asset_pages(
    *,
    user_id: int,
    deck_id: int,
    slide_numbers: list[int],
    session_id: int,
    knowledge_count: int,
    range_label: str,
) -> None:
    normalized: list[int] = []
    seen: set[int] = set()
    for raw_number in slide_numbers:
        try:
            number = int(raw_number)
        except (TypeError, ValueError):
            continue
        if number <= 0 or number in seen:
            continue
        normalized.append(number)
        seen.add(number)
    if not normalized:
        return

    rows = [
        (int(user_id), int(deck_id), number, int(session_id), int(knowledge_count), str(range_label or ""))
        for number in normalized
    ]
    execute_many(
        """
        INSERT INTO ppt_study_asset_pages (
            user_id, deck_id, slide_number, session_id, knowledge_count, range_label
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _study_asset_page_status_bar_html(
    slides: list[dict],
    *,
    selected_slide_numbers: set[int],
    completed_slide_numbers: set[int],
) -> str:
    page_numbers = _study_asset_slide_numbers(slides)
    if not page_numbers:
        return ""

    page_items: list[str] = []
    for number in page_numbers:
        is_selected = number in selected_slide_numbers
        is_completed = number in completed_slide_numbers
        classes = ["study-asset-page"]
        title_parts = [f"第 {number} 页"]
        if is_selected:
            classes.append("is-selected")
            title_parts.append("当前选择")
        if is_completed:
            classes.append("is-completed")
            title_parts.append("已生成知识卡片")
        if not is_selected and not is_completed:
            title_parts.append("未生成")
        page_items.append(
            f'<span class="{" ".join(classes)}" data-slide-number="{number}" '
            f'title="{" · ".join(title_parts)}">{number}</span>'
        )

    return f"""
    <style>
      .study-asset-page-bar {{
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        margin: 4px 0 10px;
        padding: 8px 0 2px;
      }}
      .study-asset-page {{
        min-width: 28px;
        height: 24px;
        border: 1px solid #d0d7de;
        border-radius: 6px;
        background: #f6f8fa;
        color: #57606a;
        font-size: 12px;
        font-weight: 700;
        line-height: 22px;
        text-align: center;
      }}
      .study-asset-page.is-selected {{
        border-color: #54aeef;
        background: #ddf4ff;
        color: #0969da;
      }}
      .study-asset-page.is-completed {{
        border-color: #d4a72c;
        background: #fff8c5;
        color: #7d4e00;
      }}
      .study-asset-page.is-selected.is-completed {{
        border-color: #8250df;
        background: linear-gradient(135deg, #fff8c5 0 50%, #ddf4ff 50% 100%);
        color: #6639ba;
        box-shadow: inset 0 0 0 1px rgba(130, 80, 223, 0.35);
      }}
      .study-asset-page-legend {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin: 0 0 2px;
        color: #6b7280;
        font-size: 12px;
      }}
      .study-asset-page-legend span::before {{
        content: "";
        display: inline-block;
        width: 10px;
        height: 10px;
        margin-right: 5px;
        border-radius: 3px;
        vertical-align: -1px;
      }}
      .study-asset-page-legend .legend-selected::before {{
        background: #ddf4ff;
        border: 1px solid #54aeef;
      }}
      .study-asset-page-legend .legend-completed::before {{
        background: #fff8c5;
        border: 1px solid #d4a72c;
      }}
      .study-asset-page-legend .legend-overlap::before {{
        background: linear-gradient(135deg, #fff8c5 0 50%, #ddf4ff 50% 100%);
        border: 1px solid #8250df;
      }}
    </style>
    <div class="study-asset-page-legend">
      <span class="legend-selected">当前选择</span>
      <span class="legend-completed">已生成知识卡片</span>
      <span class="legend-overlap">选择中且已生成</span>
    </div>
    <div class="study-asset-page-bar" aria-label="学习沉淀页码状态">
      {''.join(page_items)}
    </div>
    """


def _render_study_asset_page_status_bar(
    slides: list[dict],
    *,
    selected_slides: list[dict],
    completed_slide_numbers: set[int],
) -> None:
    markup = _study_asset_page_status_bar_html(
        slides,
        selected_slide_numbers=set(_study_asset_slide_numbers(selected_slides)),
        completed_slide_numbers=completed_slide_numbers,
    )
    if markup:
        st.markdown(markup, unsafe_allow_html=True)


def _select_study_asset_scope(
    deck: dict,
    slides: list[dict],
    sections: list[dict],
    today_slides: list[dict],
    *,
    completed_slide_numbers: set[int] | None = None,
) -> tuple[list[dict], str, str]:
    completed_slide_numbers = completed_slide_numbers or set()
    modes = ["手动选择今天学习页码范围"]
    if sections:
        modes.extend(["选择一个目录块", "全部目录块"])
    else:
        modes.append("全部已识别页面")
        st.warning("当前资料还没有 AI 目录分块；学习登记会按页码范围临时整理。")

    mode = st.selectbox("登记范围", modes, key=f"asset_scope_mode_{deck['id']}")
    if mode == "选择一个目录块" and sections:
        selected_index = st.selectbox(
            "选择要登记的目录块",
            [int(section["section_index"]) for section in sections],
            format_func=lambda index: _section_label(sections, index),
            key=f"asset_section_index_{deck['id']}",
        )
        section = next(item for item in sections if int(item["section_index"]) == int(selected_index))
        selected = _filter_slides_by_page_range(slides, int(section["start_slide"]), int(section["end_slide"]))
        _render_study_asset_page_status_bar(
            slides,
            selected_slides=selected,
            completed_slide_numbers=completed_slide_numbers,
        )
        return selected, _section_label(sections, int(selected_index)), mode

    if mode in {"全部目录块", "全部已识别页面"}:
        first_page = int(slides[0]["slide_number"])
        last_page = int(slides[-1]["slide_number"])
        label = "全部目录块" if sections else "全部已识别页面"
        _render_study_asset_page_status_bar(
            slides,
            selected_slides=slides,
            completed_slide_numbers=completed_slide_numbers,
        )
        return slides, f"{label}（第 {first_page}-{last_page} 页）", mode

    first_page = int(slides[0]["slide_number"])
    last_page = int(slides[-1]["slide_number"])
    if today_slides:
        default_start = min(int(slide["slide_number"]) for slide in today_slides)
        default_end = max(int(slide["slide_number"]) for slide in today_slides)
        st.caption(f"已根据今天生成过讲解的页面预设范围：第 {default_start}-{default_end} 页，可手动调整。")
    else:
        default_start = first_page
        default_end = last_page
        st.caption("今天还没有检测到新生成讲解的页面；请手动选择今天实际学习的页码范围。")

    start_page, end_page = st.slider(
        "今天已学习页码范围",
        min_value=first_page,
        max_value=last_page,
        value=(default_start, default_end),
        step=1,
        key=f"asset_manual_page_range_{deck['id']}",
    )
    selected = _filter_slides_by_page_range(slides, int(start_page), int(end_page))
    _render_study_asset_page_status_bar(
        slides,
        selected_slides=selected,
        completed_slide_numbers=completed_slide_numbers,
    )
    if not selected:
        st.warning("这个页码范围内没有已识别文字或已生成讲解的页面。")
    return selected, f"今天手动页码范围：第 {start_page}-{end_page} 页", mode


def _filter_slides_by_page_range(slides: list[dict], start_page: int, end_page: int) -> list[dict]:
    start_page, end_page = sorted((int(start_page), int(end_page)))
    return [
        slide
        for slide in slides
        if start_page <= int(slide["slide_number"]) <= end_page
    ]


def _build_study_asset_batches(
    slides: list[dict],
    *,
    sections: list[dict] | None,
    max_chars: int,
    include_ai_explanation: bool,
    split_by_sections: bool,
    fallback_range_label: str,
) -> list[dict]:
    if not split_by_sections:
        reading_content, used_pages, truncated = _build_reading_content(
            slides,
            sections=sections,
            max_chars=max_chars,
            include_ai_explanation=include_ai_explanation,
        )
        return [
            {
                "range_label": fallback_range_label,
                "reading_content": reading_content,
                "used_pages": used_pages,
                "truncated": truncated,
                "section_index": None,
                "slide_numbers": _study_asset_slide_numbers(slides[:used_pages]),
            }
        ]

    section_by_index = {int(section["section_index"]): section for section in (sections or [])}
    batches: list[dict] = []
    for section_key, group in _group_slides_for_study_assets(slides, section_by_index):
        if not group:
            continue
        section = section_by_index.get(section_key)
        label = _study_asset_batch_label(section, group)
        reading_content, used_pages, truncated = _build_reading_content(
            group,
            sections=sections,
            max_chars=max_chars,
            include_ai_explanation=include_ai_explanation,
        )
        batches.append(
            {
                "range_label": label,
                "reading_content": reading_content,
                "used_pages": used_pages,
                "truncated": truncated,
                "section_index": int(section_key) if section else None,
                "slide_numbers": _study_asset_slide_numbers(group[:used_pages]),
            }
        )
    return batches


def _study_asset_batch_label(section: dict | None, slides: list[dict]) -> str:
    start_page = int(slides[0]["slide_number"])
    end_page = int(slides[-1]["slide_number"])
    if section:
        return f"目录块 {section['section_index']}：{section.get('title') or '未命名目录块'}（第 {start_page}-{end_page} 页）"
    return f"未匹配目录块页面（第 {start_page}-{end_page} 页）"


def _merge_study_asset_batches(batch_results: list[dict], *, deck: dict, range_label: str) -> dict:
    if not batch_results:
        raise ValueError("没有可合并的学习沉淀批次。")

    first_session = dict(batch_results[0]["assets"]["study_session"])
    session_summaries = []
    blockers = []
    wrong_questions = []
    mastered = []
    cards: list[dict] = []
    seen_topics: set[tuple[str, str]] = set()
    mastery_values = []

    for item in batch_results:
        batch = item["batch"]
        assets = item["assets"]
        session = assets["study_session"]
        label = str(batch["range_label"])
        summary = str(session.get("summary") or "").strip()
        if summary:
            session_summaries.append(f"{label}：{summary}")
        for source, target in (
            ("mastered_content", mastered),
            ("blockers", blockers),
            ("wrong_questions", wrong_questions),
        ):
            value = str(session.get(source) or "").strip()
            if value:
                target.append(f"{label}：{value}")
        try:
            mastery_values.append(int(session.get("mastery")))
        except (TypeError, ValueError):
            pass
        for card in assets["knowledge_cards"]:
            normalized = dict(card)
            topic_key = (
                str(normalized.get("subject") or deck.get("subject") or "").strip(),
                str(normalized.get("topic") or "").strip(),
            )
            if topic_key in seen_topics:
                continue
            seen_topics.add(topic_key)
            cards.append(normalized)

    first_session.update(
        {
            "subject": first_session.get("subject") or deck.get("subject") or "未分类",
            "chapter": deck.get("title") or first_session.get("chapter") or "",
            "title": f"{deck.get('title') or '资料'} 学习沉淀",
            "main_question": f"这份资料在 {range_label} 中围绕哪些主线问题展开？",
            "mastered_content": "\n".join(mastered),
            "blockers": "\n".join(blockers),
            "wrong_questions": "\n".join(wrong_questions),
            "summary": "\n".join(session_summaries),
            "mastery": min(mastery_values) if mastery_values else first_session.get("mastery", 60),
            "need_review": True,
            "is_key": True,
        }
    )
    return {"study_session": first_session, "knowledge_cards": cards}


def _build_study_asset_coverage_report(batch_results: list[dict], batches: list[dict]) -> list[dict]:
    card_count_by_label = {
        str(item["batch"]["range_label"]): len(item["assets"].get("knowledge_cards") or [])
        for item in batch_results
    }
    rows = []
    for batch in batches:
        label = str(batch["range_label"])
        used_pages = int(batch.get("used_pages") or 0)
        generated_cards = int(card_count_by_label.get(label, 0))
        rows.append(
            {
                "范围": label,
                "纳入页数": used_pages,
                "生成卡片": generated_cards,
                "截断": "是" if batch.get("truncated") else "否",
                "状态": "已覆盖" if used_pages and generated_cards else "需补充",
            }
        )
    return rows


def _build_reading_content(
    slides: list[dict],
    *,
    sections: list[dict] | None = None,
    max_chars: int,
    include_ai_explanation: bool,
) -> tuple[str, int, bool]:
    chunks: list[str] = []
    used_pages = 0
    truncated = False
    current_chars = 0
    section_by_index = {int(section["section_index"]): section for section in (sections or [])}
    grouped_slides = _group_slides_for_study_assets(slides, section_by_index)

    for section_key, group in grouped_slides:
        if not group:
            continue
        section_header = _study_asset_section_header(section_by_index.get(section_key), group)
        section_started = False
        for slide in group:
            page_chunk = _study_asset_slide_chunk(slide, include_ai_explanation=include_ai_explanation)
            if not page_chunk:
                continue
            chunk = "\n\n".join([section_header if not section_started else "", page_chunk]).strip()
            extra_chars = len(chunk) + (2 if chunks else 0)
            if current_chars + extra_chars > max_chars:
                truncated = True
                if not chunks:
                    chunks.append(chunk[:max_chars].rstrip() + "\n[内容已因长度限制截断]")
                    used_pages += 1
                break
            chunks.append(chunk)
            current_chars += extra_chars
            used_pages += 1
            section_started = True
        if truncated:
            break

    return "\n\n".join(chunks).strip(), used_pages, truncated


def _group_slides_for_study_assets(
    slides: list[dict],
    section_by_index: dict[int, dict],
) -> list[tuple[int, list[dict]]]:
    grouped: list[tuple[int, list[dict]]] = []
    group_by_key: dict[int, list[dict]] = {}
    for slide in slides:
        section_index = int(slide.get("section_index") or 0)
        key = section_index if section_index in section_by_index else 0
        if key not in group_by_key:
            group_by_key[key] = []
            grouped.append((key, group_by_key[key]))
        group_by_key[key].append(slide)
    return grouped


def _study_asset_section_header(section: dict | None, slides: list[dict]) -> str:
    start_page = int(slides[0]["slide_number"])
    end_page = int(slides[-1]["slide_number"])
    if not section:
        return f"# 临时学习范围：第 {start_page}-{end_page} 页\n本范围尚未匹配到 AI 目录块。"

    key_terms = section.get("key_terms") or []
    prerequisite = section.get("prerequisite_concepts") or []
    if isinstance(key_terms, str):
        key_terms_text = key_terms
    else:
        key_terms_text = "、".join(str(item) for item in key_terms if str(item).strip())
    if isinstance(prerequisite, str):
        prerequisite_text = prerequisite
    else:
        prerequisite_text = "、".join(str(item) for item in prerequisite if str(item).strip())
    return "\n".join(
        part
        for part in [
            f"# 目录块 {section['section_index']}：{section.get('title') or '未命名目录块'}",
            f"本块完整页码：第 {section.get('start_slide')}-{section.get('end_slide')} 页",
            f"本次纳入页码：第 {start_page}-{end_page} 页",
            f"本块核心问题：{section.get('core_question') or '暂无'}",
            f"本块摘要：{section.get('summary') or '暂无'}",
            f"关键符号：{key_terms_text or '暂无'}",
            f"前置概念：{prerequisite_text or '暂无'}",
        ]
        if part
    )


def _study_asset_slide_chunk(slide: dict, *, include_ai_explanation: bool) -> str:
    slide_text = (slide.get("slide_text") or "").strip()
    explanation = (slide.get("latest_explanation") or "").strip() if include_ai_explanation else ""
    if not slide_text and not explanation:
        return ""

    highlights = _extract_markdown_highlights(explanation, slide_text)
    return "\n".join(
        part
        for part in [
            f"## 第 {slide['slide_number']} 页：{slide.get('title') or '未命名页面'}",
            f"页面类型：{slide.get('page_type') or '未标注'}",
            f"一句话摘要：{slide.get('one_sentence_summary') or '暂无'}",
            f"当前页作用：{slide.get('slide_role') or '暂无'}",
            f"考点 / 学习抓手：{slide.get('key_points') or '暂无'}",
            "本页高亮重点（知识卡片生成时优先覆盖）：\n"
            + "\n".join(f"- {item}" for item in highlights)
            if highlights
            else "",
            f"PPT/PDF 识别文字：\n{_clip_text(slide_text, 1800)}" if slide_text else "",
            f"已生成 AI 讲解：\n{_clip_text(explanation, 2400)}" if explanation else "",
        ]
        if part
    )


def _extract_markdown_highlights(*texts: str) -> list[str]:
    highlights: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in re.finditer(r"(?<!\\)==(.+?)(?<!\\)==", str(text or ""), flags=re.S):
            value = " ".join(match.group(1).split())
            if not value or value in seen:
                continue
            seen.add(value)
            highlights.append(value)
    return highlights


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[本页内容已截断]"


def _render_main_explanation(deck: dict, slide: dict) -> None:
    st.subheader("当前页主线讲解")
    user_id = int(slide.get("user_id") or deck.get("user_id") or require_login().id)
    latest = _latest_explanation(slide["id"])
    supports_image_input = _active_provider_supports_image_input(user_id=user_id)
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
                    user_id=user_id,
                )
            _save_generated_explanation(user_id, slide, _active_model_label(user_id=user_id), explanation)
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

    user_id = int(slide.get("user_id") or deck.get("user_id") or require_login().id)
    typed_question = question.strip()
    full_question = _compose_quoted_branch_question(quote, typed_question) if quote else typed_question
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
                request_timeout=PPT_INTERACTIVE_REQUEST_TIMEOUT_SECONDS,
                user_id=user_id,
            )
        add_slide_question(
            user_id,
            slide["id"],
            typed_question,
            answer,
            _active_model_label(user_id=user_id),
            quote_text=quote["selected_text"] if quote else "",
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


def _legacy_branch_question_parts(question: str) -> dict[str, str]:
    text = str(question or "").strip()
    if not all(marker in text for marker in ("引用内容", "前文上下文", "后文上下文")):
        return {}
    quote_match = re.search(r"(?:^|\n)引用内容[：:]\s*(?P<quote>[\s\S]*?)\n\s*前文上下文[：:]", text)
    question_match = re.search(r"(?:^|\n)我的问题[：:]\s*(?P<question>[\s\S]+)$", text)
    return {
        "question": question_match.group("question").strip() if question_match else "",
        "quoteText": quote_match.group("quote").strip() if quote_match else "",
    }


def _branch_question_display_parts(question: str, quote_text: str = "") -> dict[str, str]:
    text = str(question or "").strip()
    quote = str(quote_text or "").strip()
    legacy = _legacy_branch_question_parts(text)
    return {
        "question": legacy.get("question") or text,
        "quoteText": quote or legacy.get("quoteText", ""),
    }


def _display_branch_question(question: str) -> str:
    return _branch_question_display_parts(question)["question"]


def _markdown_quote_block(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in str(text or "").splitlines())


def _render_question_history_node(item: dict) -> None:
    display_parts = _branch_question_display_parts(item["question"], item.get("quote_text", ""))
    depth = int(item.get("depth") or 0)
    label = "主插问" if depth == 0 else f"{'  ' * depth}子插问 L{depth}"
    with st.container(border=True):
        st.markdown(f"**{label}:** {display_parts['question']}")
        if display_parts["quoteText"]:
            st.markdown(f"**寮曠敤锛?*\n{_markdown_quote_block(display_parts['quoteText'])}")
        st.markdown(item["answer"])
        st.caption(
            f"分类：{item.get('category') or '-'} | 状态：{item.get('status') or '-'} | "
            f"引用来源：{item.get('quote_source') or 'slide'} | "
            f"排序：{item.get('sort_order') or 0} | 模型：{item['model']} | {item['created_at']}"
        )
    for child in item.get("children") or []:
        _render_question_history_node(child)


def _flatten_question_tree_for_table(tree: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for node in tree:
        item = dict(node)
        children = item.pop("children", [])
        rows.append(item)
        rows.extend(_flatten_question_tree_for_table(children))
    return rows


def _render_question_history(slide_id: int, *, user_id: int | None = None) -> None:
    user_id = int(user_id) if user_id is not None else require_login().id
    questions = get_slide_question_tree(slide_id, user_id)
    st.subheader("本页插问记录")
    if not questions:
        st.caption("当前页还没有插问。")
        return
    for item in questions:
        _render_question_history_node(item)

    with st.expander("表格视图"):
        st.dataframe(pd.DataFrame(_flatten_question_tree_for_table(questions)), use_container_width=True, hide_index=True)


def _resume_interrupted_generation() -> dict | None:
    task = st.session_state.get("ppt_generation_task")
    if not task:
        return None

    status = apply_stop_request(task, default_status_text="生成已停止")

    if status == "completed":
        st.success(f"✅ 生成完成：{int(task.get('generated') or 0)} 页")
        skipped = int(task.get("skipped") or 0)
        failed = int(task.get("failed") or 0)
        retried = int(task.get("retried") or 0)
        if skipped or failed or retried:
            st.caption(f"跳过 {skipped} 页，失败 {failed} 页，重试 {retried} 次。")
        parallel_warning_text = _parallel_degradation_warning_text(task)
        if parallel_warning_text:
            st.warning(parallel_warning_text)
        benchmark_status_text = str(task.get("parallel_benchmark_status_text") or "")
        if benchmark_status_text:
            st.caption(benchmark_status_text)
        return task
    if status == "stopped":
        st.warning(f"⚠️ 已停止：{task.get('status_text', '生成已中断')}")
        return task
    if status != "running":
        return task

    col1, col2 = st.columns([1, 0.15])
    with col1:
        st.info("⏳ 后台生成进行中，已生成页面会自动出现在阅读器。")
        st.progress(float(task.get("progress") or 0.0), text=task.get("status_text", "生成中..."))
        st.caption(
            f"并行路数：{int(task.get('parallelism') or 1)}；"
            f"已生成 {int(task.get('generated') or 0)} 页，"
            f"跳过 {int(task.get('skipped') or 0)} 页，"
            f"失败 {int(task.get('failed') or 0)} 页，"
            f"重试 {int(task.get('retried') or 0)} 次。"
        )
    with col2:
        if st.button("停止", key="stop_generation"):
            task["stop_requested"] = True
            st.rerun()
            return task

    return task


def _auto_refresh_running_generation(task: dict | None) -> None:
    if not task or task.get("status") != "running":
        return

    # 放在阅读器渲染之后刷新，避免生成期间只显示进度条而不显示新入库讲解。
    if not _should_refresh_task(task, PPT_GENERATION_REFRESH_STATE_KEY, interval=PPT_GENERATION_REFRESH_SECONDS):
        return
    time.sleep(min(PPT_GENERATION_REFRESH_SECONDS, 0.5))
    st.rerun()


def _auto_refresh_structure_generation(task: dict | None) -> None:
    if not task:
        return

    status = str(task.get("status") or "")
    if status == "running":
        # 目录生成的进度文本可能长时间不变，但后台线程仍可能随后完成。
        # 保持一次后渲染轮询，避免页面停在旧的“生成中”DOM。
        time.sleep(0.5)
        st.rerun()
        return

    if status in {"completed", "failed", "stopped"} and task.get("_post_render_refreshed_status") != status:
        task["_post_render_refreshed_status"] = status
        st.session_state.pop(PPT_STRUCTURE_REFRESH_STATE_KEY, None)
        st.rerun()


def _should_refresh_task(task: dict, state_key: str, *, interval: float) -> bool:
    return should_refresh_task(st.session_state, task, state_key, interval=interval, now=time.monotonic())


def _generate_whole_deck_explanations(
    deck: dict,
    slides: list[dict],
    *,
    only_missing: bool,
    send_image_when_no_text: bool,
    force_image_input: bool,
    supports_image_input: bool,
    latest_by_slide_id: dict[int, dict],
    all_slides: list[dict] | None = None,
    sections: list[dict] | None = None,
    background: bool = False,
    parallelism: int = 1,
    provider_pool: list[dict] | None = None,
    adaptive_parallelism: bool = False,
    benchmark_during_generation: bool = False,
    user_id: int | None = None,
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

    user_id = int(user_id) if user_id is not None else int(deck.get("user_id") or require_login().id)
    provider_key = st.session_state.get("active_api_provider_key")
    api_key = _active_api_key()
    active_model = st.session_state.get("active_api_model", DEFAULT_MODEL)
    max_tokens = int(st.session_state.get("active_api_max_tokens", 4096))
    active_model_label = _active_model_label(user_id=user_id)
    total = len(targets)
    provider_pool = provider_pool or _build_generation_provider_pool(
        list_api_providers(enabled_only=True, user_id=user_id),
        selected_provider_keys=[str(provider_key)] if provider_key else [],
        active_provider_key=str(provider_key or ""),
    )
    provider_pool = _apply_parallel_benchmark_results(provider_pool)
    group_parallel_cap = _adaptive_generation_parallelism(provider_pool, total)
    parallelism = group_parallel_cap if adaptive_parallelism else _normalize_generation_parallelism(
        parallelism,
        total,
        max_parallelism=group_parallel_cap,
    )
    context_by_slide = build_slide_context_map(deck, all_slides or slides, sections or [])
    related_knowledge = _related_knowledge_context(deck.get("subject") or "未分类", user_id=user_id)

    if background:
        existing_task = st.session_state.get("ppt_generation_task")
        if existing_task and existing_task.get("status") == "running":
            st.info("逐页讲解正在后台生成，不会重复启动。")
            st.rerun()
            return
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
            "parallelism": parallelism,
            "provider_pool": provider_pool,
            "adaptive_parallelism": adaptive_parallelism,
            "benchmark_during_generation": benchmark_during_generation,
            "group_parallel_cap": group_parallel_cap,
            "active_model_label": active_model_label,
            "reasoning_depth": st.session_state.get("active_api_reasoning_depth"),
            "context_by_slide": context_by_slide,
            "related_knowledge": related_knowledge,
            "user_id": user_id,
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "retried": 0,
            "completed_slide_numbers": [],
            "skipped_slide_numbers": [],
            "failed_slide_numbers": [],
            "inflight_slide_numbers": [],
            "completed": False,
            "stop_requested": False,
            "max_retries": PPT_GENERATION_MAX_RETRIES,
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
        context = context_by_slide.get(int(slide["slide_number"]))
        if should_use_lightweight_explanation(slide):
            _save_lightweight_explanation(user_id, deck, slide, context, f"{active_model_label} / 分块摘要")
            generated += 1
            progress.progress(
                index / len(targets),
                text=f"第 {slide['slide_number']} 页为过渡/目录页，已写入目录块摘要。",
            )
            continue
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
            context=context,
            user_id=user_id,
            related_knowledge=related_knowledge,
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
                user_id=user_id,
            )
            _save_generated_explanation(user_id, slide, active_model_label, explanation)
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
                        _build_slide_prompt(
                            deck,
                            slide,
                            image_attached=False,
                            context=context,
                            user_id=user_id,
                            related_knowledge=related_knowledge,
                        ),
                        provider_key=provider_key,
                        api_key=api_key,
                        model_override=active_model,
                        max_output_tokens=max_tokens,
                        reasoning_depth=st.session_state.get("active_api_reasoning_depth"),
                        user_id=user_id,
                    )
                    _save_generated_explanation(user_id, slide, active_model_label, explanation)
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


def _build_generation_provider_pool(
    providers: list[dict],
    *,
    selected_provider_keys: list[str],
    active_provider_key: str | None = None,
    api_keys_by_provider: dict[str, str] | None = None,
    models_by_provider: dict[str, str] | None = None,
) -> list[dict]:
    provider_by_key = {str(provider["provider_key"]): provider for provider in providers if provider.get("enabled", 1)}
    selected = [str(provider_key) for provider_key in selected_provider_keys if str(provider_key) in provider_by_key]
    active_key = str(active_provider_key or "")
    ordered_keys: list[str] = []
    if active_key in selected:
        ordered_keys.append(active_key)
    for provider_key in selected:
        if provider_key not in ordered_keys:
            ordered_keys.append(provider_key)

    pool: list[dict] = []
    for provider_key in ordered_keys:
        provider = provider_by_key[provider_key]
        if models_by_provider is not None:
            model = str(models_by_provider.get(provider_key) or provider.get("model") or DEFAULT_MODEL)
        else:
            ensure_provider_model(provider)
            model = str(st.session_state.get(provider_model_state_key(provider_key)) or provider.get("model") or DEFAULT_MODEL)
        if api_keys_by_provider is not None:
            api_key = str(api_keys_by_provider.get(provider_key) or "")
        else:
            api_key = str(st.session_state.get(f"api_key_provider_{provider_key}") or "")
        pool.append(
            {
                "provider_key": provider_key,
                "name": provider.get("name") or provider_key,
                "provider_name": provider.get("name") or provider_key,
                "provider_type": provider.get("provider_type") or "",
                "base_url": provider.get("base_url") or "",
                "api_key_env": provider.get("api_key_env") or "",
                "auth_type": provider.get("auth_type") or "",
                "api_key": api_key,
                "active_model": model.strip() or DEFAULT_MODEL,
                "active_model_label": f"{provider.get('name') or provider_key} / {model.strip() or DEFAULT_MODEL}",
                "supports_image_input": _provider_supports_image_input(provider, model),
                "parallel_limit": _provider_parallel_limit(provider, model),
            }
        )
    return pool


def _parallel_benchmark_key(provider: dict) -> str:
    return parallel_benchmark.benchmark_key(provider)


def _parallel_benchmark_results_from_state() -> dict:
    results = st.session_state.get(PPT_PARALLEL_BENCHMARK_STATE_KEY)
    return results if isinstance(results, dict) else {}


def _apply_parallel_benchmark_results(provider_pool: list[dict], benchmark_results: dict | None = None) -> list[dict]:
    benchmark_results = benchmark_results if benchmark_results is not None else parallel_benchmark.load_benchmark_results(provider_pool)
    applied: list[dict] = []
    for provider in provider_pool:
        provider_config = dict(provider)
        result = benchmark_results.get(_parallel_benchmark_key(provider_config))
        if isinstance(result, dict):
            try:
                measured_limit = int(result.get("parallel_limit") or 0)
            except (TypeError, ValueError):
                measured_limit = 0
            if measured_limit > 0:
                provider_config["parallel_limit"] = measured_limit
                provider_config["parallel_benchmark_measured"] = True
                provider_config["parallel_benchmark_success_rate"] = result.get("success_rate")
                provider_config["parallel_benchmark_samples"] = result.get("sample_count")
        applied.append(provider_config)
    return applied


def _store_parallel_benchmark_results(benchmark_result: dict) -> None:
    for provider_result in benchmark_result.get("providers") or []:
        parallel_benchmark.save_benchmark_result(provider_result)
    st.session_state[PPT_PARALLEL_BENCHMARK_STATE_KEY] = {
        _parallel_benchmark_key(provider_result): provider_result
        for provider_result in benchmark_result.get("providers") or []
    }


def _format_parallel_benchmark_summary(provider_pool: list[dict], benchmark_results: dict | None = None) -> str:
    benchmark_results = benchmark_results if benchmark_results is not None else parallel_benchmark.load_benchmark_results(provider_pool)
    measured = []
    for provider in provider_pool:
        result = benchmark_results.get(_parallel_benchmark_key(provider))
        if not isinstance(result, dict):
            continue
        try:
            measured_limit = int(result.get("parallel_limit") or 0)
        except (TypeError, ValueError):
            measured_limit = 0
        if measured_limit > 0:
            measured.append(f"{provider.get('provider_name') or provider.get('provider_key')}：{measured_limit} 路")
    if not measured:
        return "未测速时每个 API 默认按 8 路并行估算。"
    return f"已测速：{'；'.join(measured)}。API 组上限 {sum(int(item.get('parallel_limit') or 1) for item in provider_pool)} 路。"


def _format_parallel_benchmark_result(benchmark_result: dict) -> str:
    providers = benchmark_result.get("providers") or []
    if not providers:
        return "测速完成，但没有可用 API。"
    parts = []
    for provider in providers:
        name = provider.get("provider_name") or provider.get("provider_key") or "API"
        limit = int(provider.get("parallel_limit") or 0)
        if limit > 0:
            parts.append(f"{name} {limit} 路")
        else:
            parts.append(f"{name} 测速失败")
    return f"测速完成：{'；'.join(parts)}；API 组最大稳定并行 {int(benchmark_result.get('group_parallel_limit') or 0)} 路。"


def _run_provider_parallel_probe(
    provider: dict,
    concurrency: int,
    *,
    request_func=generate_text,
) -> dict:
    return parallel_benchmark.run_provider_parallel_probe(provider, concurrency, request_func=request_func)


def _probe_provider_parallel_limit(
    provider: dict,
    *,
    max_parallelism: int = PPT_PARALLEL_BENCHMARK_MAX_PARALLELISM,
    request_func=generate_text,
) -> dict:
    previous_result = parallel_benchmark.load_benchmark_result(provider, authoritative_only=False)
    return parallel_benchmark.probe_provider_parallel_limit(
        provider,
        max_parallelism=max_parallelism,
        request_func=request_func,
        previous_result=previous_result,
    )


def _benchmark_generation_provider_pool(
    provider_pool: list[dict],
    *,
    max_parallelism: int = PPT_PARALLEL_BENCHMARK_MAX_PARALLELISM,
    request_func=generate_text,
) -> dict:
    return parallel_benchmark.benchmark_provider_pool(
        provider_pool,
        max_parallelism=max_parallelism,
        request_func=request_func,
    )


def _provider_parallel_limit(provider: dict, model: str | None = None) -> int:
    del provider, model
    return PPT_GENERATION_DEFAULT_PARALLELISM


def _adaptive_generation_parallelism(provider_pool: list[dict], total: int) -> int:
    if not provider_pool:
        return _normalize_generation_parallelism(1, total)
    group_limit = sum(max(1, int(provider.get("parallel_limit") or 1)) for provider in provider_pool)
    return _normalize_generation_parallelism(group_limit, total)


def _normalize_generation_parallelism(value: object, total: int, *, max_parallelism: int | None = None) -> int:
    try:
        requested = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        requested = 1
    try:
        target_count = int(total)
    except (TypeError, ValueError):
        target_count = 0
    if requested < 1:
        requested = 1
    if target_count <= 0:
        return 1
    try:
        cap = int(max_parallelism) if max_parallelism is not None else target_count
    except (TypeError, ValueError):
        cap = target_count
    cap = max(1, cap)
    return min(requested, target_count, cap)


def _slide_generation_result(
    slide: dict,
    status: str,
    message: str = "",
    *,
    stop: bool = False,
    error_category: str = "",
) -> dict:
    return {
        "slide_id": int(slide.get("id") or 0),
        "slide_number": int(slide.get("slide_number") or 0),
        "status": status,
        "message": message,
        "stop": stop,
        "error_category": error_category,
    }


def _save_generated_explanation(
    user_id: int,
    slide: dict,
    model: str,
    explanation: str,
    *,
    page_type: str = "",
    title: str = "",
) -> int:
    slide_number = int(slide.get("slide_number") or 0)
    metadata = extract_generated_slide_metadata(
        explanation,
        slide_number=slide_number,
        fallback_title=title or str(slide.get("title") or ""),
    )
    update_slide_learning_metadata(
        user_id,
        int(slide["id"]),
        title=metadata.get("title") or title,
        page_type=page_type or metadata.get("page_type") or "",
    )
    return add_slide_explanation(user_id, int(slide["id"]), model, explanation)


def _save_lightweight_explanation(user_id: int, deck: dict, slide: dict, context: dict | None, model: str) -> int:
    explanation = build_lightweight_explanation(deck, slide, context)
    section = (context or {}).get("section") or {}
    page_type = str(slide.get("page_type") or "过渡页")
    section_title = str(section.get("title") or "").strip()
    title = section_title if page_type in {"过渡页", "目录页"} and section_title else str(slide.get("title") or "")
    return _save_generated_explanation(
        user_id,
        slide,
        model,
        explanation,
        page_type=page_type,
        title=title,
    )


def _generation_error_message(slide: dict, exc: Exception) -> str:
    slide_number = int(slide.get("slide_number") or 0)
    if is_quota_error(exc):
        return f"第 {slide_number} 页生成失败：检测到 API 额度或上游余额不足，已停止后续页面生成。"
    if isinstance(exc, AIServiceError) and exc.category == "rate_limit":
        return f"第 {slide_number} 页生成失败：触发频率限制，已停止后续调度；请把并行生成路数调低后重试。"
    if isinstance(exc, AIServiceError) and exc.category == "model_not_found":
        return f"第 {slide_number} 页生成失败：当前模型在这个 Provider 下不可用，已停止后续页面生成。"
    return f"第 {slide_number} 页生成失败：{exc}"


def _default_generation_provider_from_task(task: dict) -> dict:
    parallel_limit = task.get("parallelism") or 1
    try:
        parallel_limit = int(parallel_limit)
    except (TypeError, ValueError):
        parallel_limit = 1
    return {
        "provider_key": task.get("provider_key"),
        "provider_name": task.get("provider_key") or "当前 Provider",
        "api_key": task.get("api_key"),
        "active_model": task.get("active_model"),
        "active_model_label": str(task.get("active_model_label") or task.get("active_model") or DEFAULT_MODEL),
        "supports_image_input": bool(task.get("supports_image_input")),
        "parallel_limit": max(1, parallel_limit),
    }


def _generate_slide_explanation_from_task(
    task: dict,
    deck: dict,
    slide: dict,
    provider_config: dict | None = None,
) -> dict:
    provider_config = provider_config or _default_generation_provider_from_task(task)
    context_by_slide = task.get("context_by_slide") or {}
    slide_number = int(slide.get("slide_number") or 0)
    context = context_by_slide.get(slide_number) or context_by_slide.get(str(slide_number))
    user_id = int(task.get("user_id") or 0)
    active_model_label = str(provider_config.get("active_model_label") or task.get("active_model_label") or "")
    reasoning_depth = task.get("reasoning_depth")
    related_knowledge = str(task.get("related_knowledge") or "")

    if should_use_lightweight_explanation(slide):
        _save_lightweight_explanation(user_id, deck, slide, context, f"{active_model_label} / 分块摘要")
        return _slide_generation_result(slide, "generated", f"第 {slide_number} 页已写入目录块摘要。")

    image_paths = _image_paths_for_generation(
        slide,
        bool(task.get("send_image_when_no_text")),
        supports_image_input=bool(provider_config.get("supports_image_input")),
        force_image_input=bool(task.get("force_image_input")),
    )
    if task.get("force_image_input") and not image_paths:
        return _slide_generation_result(
            slide,
            "skipped",
            f"第 {slide_number} 页直接发原图模式没有可用图片，已跳过。",
        )
    if _is_text_empty(slide) and not image_paths:
        return _slide_generation_result(
            slide,
            "skipped",
            f"第 {slide_number} 页没有提取到文字，且当前模型不能读图片，已跳过。",
        )

    prompt = _build_slide_prompt(
        deck,
        slide,
        image_attached=bool(image_paths),
        ignore_extracted_text=bool(task.get("force_image_input")),
        context=context,
        user_id=user_id,
        related_knowledge=related_knowledge,
    )
    try:
        explanation = generate_text(
            prompt,
            provider_key=provider_config.get("provider_key"),
            api_key=provider_config.get("api_key"),
            model_override=provider_config.get("active_model"),
            image_paths=image_paths,
            max_output_tokens=int(task.get("max_tokens") or 4096),
            reasoning_depth=reasoning_depth,
            user_id=user_id,
        )
        _save_generated_explanation(user_id, slide, active_model_label, explanation)
        return _slide_generation_result(slide, "generated", f"第 {slide_number} 页讲解已生成。")
    except AIServiceError as exc:
        if image_paths and _is_image_input_error(exc):
            if task.get("force_image_input"):
                return _slide_generation_result(
                    slide,
                    "failed",
                    f"第 {slide_number} 页：当前模型拒绝图片输入，准备换用其它 Provider 重试。",
                    error_category=exc.category,
                )
            if _is_text_empty(slide):
                return _slide_generation_result(
                    slide,
                    "skipped",
                    f"第 {slide_number} 页没有可用文字，文本模式无法生成有效讲解，已跳过。",
                )
            try:
                fallback_prompt = _build_slide_prompt(
                    deck,
                    slide,
                    image_attached=False,
                    context=context,
                    user_id=user_id,
                    related_knowledge=related_knowledge,
                )
                explanation = generate_text(
                    fallback_prompt,
                    provider_key=provider_config.get("provider_key"),
                    api_key=provider_config.get("api_key"),
                    model_override=provider_config.get("active_model"),
                    max_output_tokens=int(task.get("max_tokens") or 4096),
                    reasoning_depth=reasoning_depth,
                    user_id=user_id,
                )
                _save_generated_explanation(user_id, slide, active_model_label, explanation)
                return _slide_generation_result(slide, "generated", f"第 {slide_number} 页已回退文本模式生成。")
            except AIServiceError as retry_exc:
                return _slide_generation_result(
                    slide,
                    "failed",
                    _generation_error_message(slide, retry_exc),
                    error_category=retry_exc.category,
                )
        return _slide_generation_result(
            slide,
            "failed",
            _generation_error_message(slide, exc),
            error_category=exc.category,
        )


def _update_generation_task_progress(
    task: dict,
    *,
    processed: int,
    total: int,
    generated: int,
    skipped: int,
    failed: int,
    inflight: list[int],
    message: str = "",
) -> None:
    task.update(
        generation_progress_patch(
            processed=processed,
            total=total,
            generated=generated,
            skipped=skipped,
            failed=failed,
            inflight=inflight,
            message=message,
        )
    )


def _provider_pool_from_task(task: dict) -> list[dict]:
    pool = task.get("provider_pool")
    if isinstance(pool, list) and pool:
        return pool
    return [_default_generation_provider_from_task(task)]


def _provider_can_handle_slide(task: dict, slide: dict, provider: dict) -> bool:
    if task.get("force_image_input"):
        return bool(provider.get("supports_image_input"))
    if task.get("send_image_when_no_text") and _is_text_empty(slide):
        return bool(provider.get("supports_image_input"))
    return True


def _eligible_provider_states(task: dict, slide: dict, provider_states: list[dict]) -> list[dict]:
    return [
        state
        for state in provider_states
        if _provider_can_handle_slide(task, slide, state["provider"])
    ]


def _available_provider_state(candidates: list[dict], failed_provider_keys: set[str]) -> dict | None:
    fresh_candidates = [
        state
        for state in candidates
        if state["provider_key"] not in failed_provider_keys and state["running"] < state["parallel_limit"]
    ]
    if fresh_candidates:
        return min(fresh_candidates, key=lambda state: (state["running"], state["order"]))

    fallback_candidates = [
        state
        for state in candidates
        if state["running"] < state["parallel_limit"]
    ]
    if fallback_candidates:
        return min(fallback_candidates, key=lambda state: (state["running"], state["order"]))
    return None


def _skip_job_without_provider(
    task: dict,
    job: dict,
    *,
    processed: int,
    total: int,
    generated: int,
    skipped: int,
    failed: int,
) -> tuple[int, int]:
    slide = job["slide"]
    slide_number = int(slide.get("slide_number") or 0)
    processed += 1
    skipped += 1
    task.setdefault("skipped_slide_numbers", []).append(slide_number)
    _update_generation_task_progress(
        task,
        processed=processed,
        total=total,
        generated=generated,
        skipped=skipped,
        failed=failed,
        inflight=[],
        message=f"第 {slide_number} 页没有可用 Provider，已跳过。",
    )
    return processed, skipped


def _finalize_generation_parallel_benchmark(task: dict, stats: dict[str, dict]) -> None:
    results = parallel_benchmark.finalize_generation_benchmark_stats(
        stats,
        min_samples=PPT_INLINE_BENCHMARK_MIN_SLIDES,
    )
    task["parallel_benchmark_results"] = results
    if not task.get("benchmark_during_generation"):
        return
    for result in results:
        parallel_benchmark.save_benchmark_result(result)
    authoritative = [result for result in results if result.get("is_authoritative")]
    if authoritative:
        task["parallel_benchmark_status_text"] = "已根据本次真实生成样本更新 API 并行路数记录。"
    else:
        task["parallel_benchmark_status_text"] = "本次真实生成样本不足或成功率不足，已记录本地样本，但未绑定为最大并行路数。"


def _parallel_degradation_warning_text(task: dict) -> str:
    warnings = task.get("parallel_degradation_warnings") or []
    if not warnings:
        return ""
    parts = []
    for item in warnings:
        name = item.get("provider_name") or item.get("provider_key") or "API"
        old_limit = item.get("from") or "?"
        new_limit = item.get("to") or "?"
        parts.append(f"{name}：{old_limit} -> {new_limit}")
    return f"检测到高错误率，已动态降低并行路数（{'；'.join(parts)}）。现有最大并行路数记录可能不适用，建议重新测速。"


def _background_generation_worker(task: dict, deck: dict, targets: list[dict]) -> None:
    generated = 0
    skipped = 0
    failed = 0
    retried = int(task.get("retried") or 0)
    max_retries = max(0, int(task.get("max_retries") if task.get("max_retries") is not None else PPT_GENERATION_MAX_RETRIES))
    processed = 0
    total = len(targets)
    if total <= 0:
        task["status"] = "completed"
        task["progress"] = 1.0
        task["generated"] = 0
        task["skipped"] = 0
        task["failed"] = 0
        task["retried"] = 0
        task["status_text"] = "没有需要生成的页面。"
        return

    provider_pool = _provider_pool_from_task(task)
    provider_states = []
    for order, provider in enumerate(provider_pool):
        parallel_limit = max(1, int(provider.get("parallel_limit") or 1))
        provider_states.append(
            {
                "order": order,
                "provider": provider,
                "provider_key": str(provider.get("provider_key") or ""),
                "parallel_limit": parallel_limit,
                "running": 0,
            }
        )
    group_parallel_cap = _adaptive_generation_parallelism(provider_pool, total)
    parallelism = _normalize_generation_parallelism(
        task.get("parallelism"),
        total,
        max_parallelism=group_parallel_cap,
    )
    task["parallelism"] = parallelism
    task["group_parallel_cap"] = group_parallel_cap
    pending = [
        {
            "slide": slide,
            "attempt": 0,
            "failed_provider_keys": set(),
        }
        for slide in targets
    ]
    future_to_slide = {}
    generation_benchmark_stats = parallel_benchmark.new_generation_benchmark_stats(provider_pool)
    benchmark_during_generation = bool(task.get("benchmark_during_generation"))

    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        while pending or future_to_slide:
            if task.get("stop_requested"):
                pending.clear()

            while pending and len(future_to_slide) < parallelism and not task.get("stop_requested"):
                scheduled = False
                for index, job in enumerate(list(pending)):
                    slide = job["slide"]
                    candidates = _eligible_provider_states(task, slide, provider_states)
                    if not candidates:
                        pending.pop(index)
                        processed, skipped = _skip_job_without_provider(
                            task,
                            job,
                            processed=processed,
                            total=total,
                            generated=generated,
                            skipped=skipped,
                            failed=failed,
                        )
                        scheduled = True
                        break
                    provider_state = _available_provider_state(candidates, job["failed_provider_keys"])
                    if not provider_state:
                        continue
                    pending.pop(index)
                    provider_state["running"] += 1
                    future = executor.submit(
                        _generate_slide_explanation_from_task,
                        task,
                        deck,
                        slide,
                        provider_state["provider"],
                    )
                    future_to_slide[future] = (job, provider_state)
                    parallel_benchmark.record_generation_schedule(
                        generation_benchmark_stats,
                        provider_state["provider"],
                        provider_state["running"],
                    )
                    scheduled = True
                    break
                if not scheduled:
                    break

            inflight = [int(job["slide"].get("slide_number") or 0) for job, _ in future_to_slide.values()]
            _update_generation_task_progress(
                task,
                processed=processed,
                total=total,
                generated=generated,
                skipped=skipped,
                failed=failed,
                inflight=inflight,
            )
            if not future_to_slide:
                break

            done, _ = wait(future_to_slide, timeout=0.25, return_when=FIRST_COMPLETED)
            if not done:
                continue

            for future in done:
                job, provider_state = future_to_slide.pop(future)
                provider_state["running"] = max(0, provider_state["running"] - 1)
                slide = job["slide"]
                try:
                    result = future.result()
                except Exception as exc:
                    result = _slide_generation_result(
                        slide,
                        "failed",
                        f"第 {int(slide.get('slide_number') or 0)} 页生成失败：{exc}",
                        error_category=parallel_benchmark.classify_error_category(exc),
                    )

                status = result.get("status")
                slide_number = int(result.get("slide_number") or 0)
                parallel_benchmark.record_generation_outcome(
                    generation_benchmark_stats,
                    provider_state["provider"],
                    status=str(status or ""),
                    error_category=str(result.get("error_category") or ""),
                )
                if parallel_benchmark.maybe_degrade_provider_parallel_limit(provider_state, generation_benchmark_stats):
                    task.setdefault("parallel_degradation_warnings", []).append(
                        {
                            "provider_key": provider_state["provider_key"],
                            "provider_name": provider_state["provider"].get("provider_name") or provider_state["provider_key"],
                            "from": generation_benchmark_stats[_parallel_benchmark_key(provider_state["provider"])].get("degraded_from"),
                            "to": generation_benchmark_stats[_parallel_benchmark_key(provider_state["provider"])].get("degraded_to"),
                        }
                    )
                    parallel_benchmark.mark_benchmark_invalidated(
                        provider_state["provider"],
                        "generation_high_error_rate",
                    )
                elif benchmark_during_generation and parallel_benchmark.maybe_raise_provider_parallel_limit(
                    provider_state,
                    generation_benchmark_stats,
                    total_targets=total,
                ):
                    task.setdefault("parallel_raise_events", []).append(
                        {
                            "provider_key": provider_state["provider_key"],
                            "provider_name": provider_state["provider"].get("provider_name") or provider_state["provider_key"],
                            "to": provider_state["parallel_limit"],
                        }
                    )
                if task.get("parallel_degradation_warnings") or task.get("parallel_raise_events"):
                    group_parallel_cap = max(1, sum(max(1, int(state.get("parallel_limit") or 1)) for state in provider_states))
                    parallelism = _normalize_generation_parallelism(parallelism, total, max_parallelism=group_parallel_cap)
                    if benchmark_during_generation:
                        parallelism = group_parallel_cap
                        parallelism = _normalize_generation_parallelism(parallelism, total, max_parallelism=group_parallel_cap)
                    task["parallelism"] = parallelism
                    task["group_parallel_cap"] = group_parallel_cap
                if status == "generated":
                    processed += 1
                    generated += 1
                    task.setdefault("completed_slide_numbers", []).append(slide_number)
                elif status == "skipped":
                    processed += 1
                    skipped += 1
                    task.setdefault("skipped_slide_numbers", []).append(slide_number)
                else:
                    next_attempt = int(job.get("attempt") or 0) + 1
                    if not task.get("stop_requested") and next_attempt <= max_retries:
                        retry_job = {
                            "slide": slide,
                            "attempt": next_attempt,
                            "failed_provider_keys": set(job.get("failed_provider_keys") or set()) | {provider_state["provider_key"]},
                        }
                        pending.append(retry_job)
                        retried += 1
                        task["retried"] = retried
                        _update_generation_task_progress(
                            task,
                            processed=processed,
                            total=total,
                            generated=generated,
                            skipped=skipped,
                            failed=failed,
                            inflight=[int(item["slide"].get("slide_number") or 0) for item, _ in future_to_slide.values()],
                            message=f"第 {slide_number} 页生成失败，已重新加入队列（第 {retry_job['attempt']} 次重试）。",
                        )
                        continue
                    processed += 1
                    failed += 1
                    task.setdefault("failed_slide_numbers", []).append(slide_number)
                    if not task.get("stop_requested"):
                        _update_generation_task_progress(
                            task,
                            processed=processed,
                            total=total,
                            generated=generated,
                            skipped=skipped,
                            failed=failed,
                            inflight=[int(item["slide"].get("slide_number") or 0) for item, _ in future_to_slide.values()],
                            message=f"第 {slide_number} 页连续失败，已达到最大重试次数 {max_retries}。",
                        )

                if result.get("stop"):
                    task["stop_requested"] = True
                    pending.clear()

                _update_generation_task_progress(
                    task,
                    processed=processed,
                    total=total,
                    generated=generated,
                    skipped=skipped,
                    failed=failed,
                    inflight=[int(item["slide"].get("slide_number") or 0) for item, _ in future_to_slide.values()],
                    message=str(result.get("message") or ""),
                )

    task["inflight_slide_numbers"] = []
    task["generated"] = generated
    task["skipped"] = skipped
    task["failed"] = failed
    task["retried"] = retried
    task["processed"] = processed
    _finalize_generation_parallel_benchmark(task, generation_benchmark_stats)
    parallel_warning_text = _parallel_degradation_warning_text(task)
    benchmark_status_text = str(task.get("parallel_benchmark_status_text") or "")
    if task.get("stop_requested"):
        task["status"] = "stopped"
        task["progress"] = (processed / total) if total else 1.0
        task["status_text"] = f"已停止：完成 {processed} / {total} 页，生成 {generated} 页，跳过 {skipped} 页，失败 {failed} 页，重试 {retried} 次。"
        if parallel_warning_text:
            task["status_text"] += f" {parallel_warning_text}"
        return

    task["status"] = "completed"
    task["progress"] = 1.0
    task["status_text"] = f"生成完成：{generated} 页，跳过 {skipped} 页，失败 {failed} 页，重试 {retried} 次。"
    extra_messages = [text for text in (parallel_warning_text, benchmark_status_text) if text]
    if extra_messages:
        task["status_text"] += " " + " ".join(extra_messages)


def _build_reader_payload(
    slides: list[dict],
    latest_by_slide_id: dict[int, dict],
    question_by_slide_id: dict[int, list[dict]],
    *,
    image_slide_numbers: set[int] | None = None,
) -> list[dict]:
    payload = []
    image_slide_numbers = image_slide_numbers or set()
    for slide in slides:
        image_path = Path(slide.get("image_path") or "")
        latest = latest_by_slide_id.get(int(slide["id"]))
        slide_text = _display_slide_text(slide)
        slide_title = slide.get("title") or f"第 {slide['slide_number']} 页"
        bookmark_title = str(slide.get("bookmark_title") or "").strip() or slide_title

        image_available = image_path.exists() and image_path.is_file()
        if image_available:
            image_data = _reader_image_url(image_path)
        else:
            image_data = ""

        payload.append(
            {
                "slideNumber": int(slide["slide_number"]),
                "title": slide_title,
                "image": image_data,
                "imageAvailable": image_available,
                "explanation": latest["explanation"] if latest else "本页还没有 AI 讲解。",
                "hasExplanation": bool(latest),
                "slideText": slide_text,
                "model": latest["model"] if latest else "",
                "createdAt": latest["created_at"] if latest else "",
                "sectionIndex": int(slide.get("section_index") or 0),
                "pageType": slide.get("page_type") or "",
                "summary": slide.get("one_sentence_summary") or "",
                "slideRole": slide.get("slide_role") or "",
                "keyPoints": slide.get("key_points") or "",
                "bookmarkEnabled": bool(slide.get("bookmark_enabled")),
                "bookmarkTitle": bookmark_title,
                "questions": question_by_slide_id.get(int(slide["id"]), []),
            }
        )
    return payload


def _reader_sections_payload(sections: list[dict]) -> list[dict]:
    return [
        {
            "sectionIndex": int(section["section_index"]),
            "title": section.get("title") or f"目录块 {section['section_index']}",
            "startSlide": int(section["start_slide"]),
            "endSlide": int(section["end_slide"]),
            "coreQuestion": section.get("core_question") or "",
            "summary": section.get("summary") or "",
        }
        for section in sections
    ]


def _build_synced_reader_html(deck: dict, payload: list[dict]) -> str:
    pages_json = json.dumps(payload, ensure_ascii=False)
    deck_id = int(deck["id"])
    title = html.escape(deck.get("title") or "学习资料")
    subject = html.escape(deck.get("subject") or "未分类")
    active_model = html.escape(_active_model_label(user_id=int(deck.get("user_id") or require_login().id)))
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
      overflow-y: visible;
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


def _reader_image_url(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    stat = path.stat()
    return _cached_reader_image_url(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=READER_IMAGE_URL_CACHE_MAX_SLIDES)
def _cached_reader_image_url(path_text: str, mtime_ns: int, size: int) -> str:
    source = Path(path_text)
    if not source.exists() or not source.is_file():
        return ""
    suffix = source.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        suffix = ".png"
    digest = hashlib.sha1(f"{path_text}|{mtime_ns}|{size}".encode("utf-8", "surrogatepass")).hexdigest()
    target_dir = SYNCED_READER_IMAGE_CACHE_PATH / digest[:2]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}{suffix}"
    if not target.exists() or target.stat().st_size != size:
        shutil.copyfile(source, target)
    return f"{SYNCED_READER_IMAGE_URL_BASE}/{digest[:2]}/{target.name}?v={mtime_ns}"


def _image_exists(slide: dict) -> bool:
    image_path = slide.get("image_path") or ""
    return bool(image_path and Path(image_path).exists())


def _deck_can_render_page_images(deck: dict) -> bool:
    file_path = str(deck.get("file_path") or "").strip()
    if not file_path:
        return False
    path = Path(file_path)
    if path.suffix.lower() not in {".pptx", ".pdf"}:
        return False
    return path.exists()


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
    return latest_explanation(require_login().id, slide_id)


def _latest_explanations_by_slide_ids(slide_ids: list[int]) -> dict[int, dict]:
    return latest_explanations_by_slide_ids(require_login().id, slide_ids)


def _question_tree_node_payload(row: dict) -> dict:
    children = row.get("children") or []
    return {
        **_branch_question_display_parts(row["question"], row.get("quote_text", "")),
        "id": row.get("id"),
        "rootQuestionId": row.get("root_question_id") or row.get("id"),
        "parentQuestionId": row.get("parent_question_id"),
        "depth": int(row.get("depth") or 0),
        "quoteSource": row.get("quote_source") or "slide",
        "quoteSourceQuestionId": row.get("quote_source_question_id"),
        "answer": row["answer"],
        "model": row["model"],
        "category": row["category"],
        "status": row["status"],
        "knowledgeId": row.get("knowledge_id"),
        "convertedToKnowledge": bool(row.get("converted_to_knowledge")),
        "understood": bool(row.get("understood")),
        "needReview": bool(row.get("need_review")),
        "sortOrder": row["sort_order"],
        "createdAt": row["created_at"],
        "children": [_question_tree_node_payload(child) for child in children],
    }


def _questions_by_slide_ids(slide_ids: list[int]) -> dict[int, list[dict]]:
    user_id = require_login().id
    return {
        int(slide_id): [
            _question_tree_node_payload(row)
            for row in get_slide_question_tree(int(slide_id), user_id)
        ]
        for slide_id in slide_ids
    }


def _build_slide_prompt(
    deck: dict,
    slide: dict,
    *,
    image_attached: bool = False,
    ignore_extracted_text: bool = False,
    context: dict | None = None,
    user_id: int | None = None,
    related_knowledge: str | None = None,
) -> str:
    slide_text = "" if ignore_extracted_text else _display_slide_text(slide)
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
            "context_package": format_slide_context_package(context),
            "related_knowledge": related_knowledge
            if related_knowledge is not None
            else _related_knowledge_context(subject, user_id=user_id),
        },
    )


def _related_knowledge_context(subject: str, limit: int = 8, *, user_id: int | None = None) -> str:
    if not subject or subject == "未分类":
        return "暂无同科目知识卡片。"

    user_id = int(user_id or require_login().id)
    cards = fetch_all(
        """
        SELECT id, topic, core_question, one_sentence, mastery
        FROM knowledge_cards
        WHERE user_id = ? AND subject = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, subject, limit),
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


def _build_branch_prompt(
    deck: dict,
    slide: dict,
    latest: dict | None,
    question: str,
    *,
    context: dict | None = None,
) -> str:
    return render_template(
        "ppt_branch_question.md",
        {
            "subject": deck.get("subject") or "未分类",
            "deck_title": deck["title"],
            "slide_number": str(slide["slide_number"]),
            "slide_title": slide["title"] or "未命名页面",
            "slide_text": _display_slide_text(slide) or "这一页没有解析到文字。",
            "main_explanation": latest["explanation"] if latest else "尚未生成主线讲解。",
            "context_package": format_slide_context_package(context),
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


def _display_slide_text(slide: dict) -> str:
    text = str(slide.get("slide_text") or "")
    notes = str(slide.get("notes") or "")
    if "extractor=mineru" not in notes:
        return text
    return "\n".join(normalize_mineru_math_text(line) for line in text.splitlines())


def _pdf_extraction_method_options(mineru_status: MinerUStatus) -> list[tuple[str, str]]:
    options = [("local", "本地增强抽取（默认）")]
    if mineru_status.available:
        options.append(("mineru", "MinerU 高精度抽取（可选）"))
    return options


def _active_api_key() -> str:
    provider_key = st.session_state.get("active_api_provider_key")
    return st.session_state.get(f"api_key_provider_{provider_key}", "")


def _is_text_empty(slide: dict) -> bool:
    return not (slide.get("slide_text") or "").strip()


def _provider_supports_image_input(provider: dict, model: str | None = None) -> bool:
    override = str(provider.get("vision_capability") or "auto").strip().lower()
    if override == "supported":
        return True
    if override == "unsupported":
        return False

    if provider.get("provider_type") != "openai_chat":
        return False

    model = str(model or provider.get("model") or "").lower()
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


def _active_provider_supports_image_input(*, user_id: int | None = None) -> bool:
    user_id = int(user_id) if user_id is not None else require_login().id
    provider_key = st.session_state.get("active_api_provider_key")
    providers = list_api_providers(user_id=user_id)
    provider = next((item for item in providers if item["provider_key"] == provider_key), None)
    if not provider:
        return False
    model = str(st.session_state.get("active_api_model") or provider.get("model") or "")
    return _provider_supports_image_input(provider, model)


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


def _active_model_label(*, user_id: int | None = None) -> str:
    user_id = int(user_id) if user_id is not None else require_login().id
    provider_key = st.session_state.get("active_api_provider_key")
    model = st.session_state.get("active_api_model", DEFAULT_MODEL)
    providers = list_api_providers(user_id=user_id)
    provider = next((item for item in providers if item["provider_key"] == provider_key), None)
    if not provider:
        return model
    return f"{provider['name']} / {model}"
