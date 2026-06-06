from __future__ import annotations

from pathlib import Path

import streamlit as st

from db import fetch_all
from services.auth_service import require_login
from services.export_manifest_service import PUBLIC_EXCLUDED_SECTIONS
from services.ppt_explanation_export_service import export_deck_share_package


PUBLIC_BOUNDARY_TEXT = "本分享包只包含 PPT 页面内容和 AI 逐页讲解，不包含你的插问、知识卡片、错因、复习任务、掌握度或个人学习记录。"


def render() -> None:
    user = require_login()
    st.title("PPT 讲解分享包")
    st.info(PUBLIC_BOUNDARY_TEXT)

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
        st.warning("还没有可导出的 PPT / PDF deck。")
        return

    subjects = sorted({deck.get("subject") or "未分类" for deck in decks})
    selected_subject = st.selectbox("选择科目", subjects)
    subject_decks = [deck for deck in decks if (deck.get("subject") or "未分类") == selected_subject]
    deck_by_id = {int(deck["id"]): deck for deck in subject_decks}
    deck_id = st.selectbox(
        "选择 PPT / PDF deck",
        list(deck_by_id),
        format_func=lambda item_id: f"#{item_id} {deck_by_id[item_id].get('title') or deck_by_id[item_id].get('filename')}",
    )
    deck = deck_by_id[int(deck_id)]
    st.metric("将导出的 slide 数量", int(deck.get("actual_slide_count") or deck.get("slide_count") or 0))

    with st.expander("隐私排除清单", expanded=True):
        st.write("公开分享包不会读取或打包以下个人学习数据：")
        st.code(", ".join(PUBLIC_EXCLUDED_SECTIONS), language="text")

    include_original = st.checkbox("包含原始 PPT / PDF 文件", value=False)
    if include_original:
        st.warning("请确认你有权分享原始课件。只有主动勾选时，原始 PPT/PDF 才会进入 attachments/。")

    if st.button("生成公开 ZIP", type="primary"):
        try:
            result = export_deck_share_package(user.id, int(deck_id), include_original=include_original)
        except Exception as exc:
            st.error(f"生成分享包失败：{exc}")
            return
        st.success(f"分享包已生成：{result['slide_count']} 页。")
        zip_path = Path(result["zip_path"])
        st.code(str(zip_path), language="text")
        st.download_button(
            "下载 ZIP",
            data=zip_path.read_bytes(),
            file_name=zip_path.name,
            mime="application/zip",
        )
