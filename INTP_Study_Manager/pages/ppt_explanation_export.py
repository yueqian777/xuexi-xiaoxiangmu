from __future__ import annotations

from pathlib import Path

import streamlit as st

from db import fetch_all
from services.auth_service import require_login
from services.export_manifest_service import PUBLIC_EXCLUDED_SECTIONS
from services.ppt_explanation_export_service import export_decks_share_package


PUBLIC_EXCLUDED_SECTION_LABELS = {
    "slide_questions": "PPT 页面的插问和追问",
    "branch_questions": "学习会话里的分支问题",
    "knowledge_cards": "知识卡片",
    "knowledge_links": "知识卡片之间的关联",
    "mistakes": "错题和错因记录",
    "review_tasks": "复习任务和复习计划",
    "study_sessions": "个人学习记录",
    "daily_review_logs": "每日复习日志",
    "daily_ai_review_plans": "每日 AI 复习计划",
    "parking_lot": "暂存问题",
    "mastery": "掌握度数据",
    "api_settings": "API 设置",
    "api_providers": "API provider 配置",
    "api_keys": "API Key 和密钥文件",
}

PPT_SHARE_EXPORT_COPY = {
    "title": "PPT 讲解分享包",
    "boundary": (
        "公开分享包：只给别人看 PPT 页面、页面图片和 AI 逐页讲解；不会导出你的学习记录，"
        "也不会导出插问、知识卡片、错因、复习任务、掌握度或账号/API 配置。"
    ),
    "empty": "还没有可导出的 PPT / PDF。",
    "subject_label": "先按科目筛选",
    "deck_label": "选择要打包的 PPT / PDF（可多选）",
    "selected_decks_metric": "选中的 PPT/PDF",
    "selected_slides_metric": "将导出的页面数",
    "privacy_expander": "不会进入公开分享包的内容",
    "privacy_intro": "下面这些内容只留在你的本地学习库里，不会写入 ZIP：",
    "include_original_label": "附带原始 PPT/PDF 文件（默认关闭）",
    "include_original_help": "只有确认版权允许、并且希望对方拿到原始课件时再打开。",
    "include_original_warning": "请确认你有权分享原始课件。只有主动勾选时，原始 PPT/PDF 才会进入 ZIP。",
    "no_selection": "至少选择一个 PPT / PDF 后才能生成分享包。",
    "button": "生成公开分享 ZIP",
    "success_template": "分享包已生成：{deck_count} 个 PPT/PDF，{slide_count} 页。",
    "download": "下载 ZIP",
}


def get_ppt_share_export_copy() -> dict[str, object]:
    return PPT_SHARE_EXPORT_COPY


def render() -> None:
    user = require_login()
    copy = get_ppt_share_export_copy()
    st.title(copy["title"])
    st.info(copy["boundary"])

    decks = fetch_all(
        """
        SELECT d.*, COUNT(ps.id) AS actual_slide_count
        FROM ppt_decks d
        LEFT JOIN ppt_slides ps ON ps.deck_id = d.id AND ps.user_id = d.user_id
        WHERE d.user_id = ?
        GROUP BY d.id
        ORDER BY d.subject ASC, d.created_at DESC, d.id DESC
        """,
        (user.id,),
    )
    if not decks:
        st.warning(copy["empty"])
        return

    subjects = sorted({deck.get("subject") or "未分类" for deck in decks})
    selected_subject = st.selectbox(copy["subject_label"], subjects)
    subject_decks = [deck for deck in decks if (deck.get("subject") or "未分类") == selected_subject]
    deck_by_id = {int(deck["id"]): deck for deck in subject_decks}
    deck_options = list(deck_by_id)
    selected_deck_ids = st.multiselect(
        copy["deck_label"],
        list(deck_by_id),
        default=deck_options[:1],
        format_func=lambda item_id: _format_deck_option(deck_by_id[item_id]),
    )
    selected_decks = [deck_by_id[int(deck_id)] for deck_id in selected_deck_ids]
    selected_slide_count = sum(_deck_slide_count(deck) for deck in selected_decks)
    col_count, col_slides = st.columns(2)
    col_count.metric(copy["selected_decks_metric"], len(selected_decks))
    col_slides.metric(copy["selected_slides_metric"], selected_slide_count)

    with st.expander(copy["privacy_expander"], expanded=False):
        st.write(copy["privacy_intro"])
        for section in PUBLIC_EXCLUDED_SECTIONS:
            st.write(f"- {PUBLIC_EXCLUDED_SECTION_LABELS.get(section, section)}")

    include_original = st.checkbox(
        copy["include_original_label"],
        value=False,
        help=copy["include_original_help"],
    )
    if include_original:
        st.warning(copy["include_original_warning"])

    if not selected_deck_ids:
        st.warning(copy["no_selection"])

    if st.button(copy["button"], type="primary", disabled=not selected_deck_ids):
        try:
            result = export_decks_share_package(
                user.id,
                [int(deck_id) for deck_id in selected_deck_ids],
                include_original=include_original,
            )
        except Exception as exc:
            st.error(f"生成分享包失败：{exc}")
            return
        st.success(
            copy["success_template"].format(
                deck_count=result.get("deck_count") or len(selected_deck_ids),
                slide_count=result["slide_count"],
            )
        )
        zip_path = Path(result["zip_path"])
        st.code(str(zip_path), language="text")
        st.download_button(
            copy["download"],
            data=zip_path.read_bytes(),
            file_name=zip_path.name,
            mime="application/zip",
        )


def _format_deck_option(deck: dict) -> str:
    title = deck.get("title") or deck.get("filename") or "未命名 PPT/PDF"
    slide_count = _deck_slide_count(deck)
    return f"#{deck['id']} {title}（{slide_count} 页）"


def _deck_slide_count(deck: dict) -> int:
    return int(deck.get("actual_slide_count") or deck.get("slide_count") or 0)
