from __future__ import annotations

from pathlib import Path

import streamlit as st

from db import fetch_all
from services.auth_service import require_login
from services.markdown_export_service import export_obsidian_vault


MARKDOWN_EXPORT_COPY = {
    "title": "私人 Markdown / Obsidian 导出",
    "caption": "单向生成私人 Markdown / Obsidian 知识库，适合用 Obsidian、VS Code、Typora 或 Git 备份阅读。",
    "subject_label": "导出哪些科目",
    "all_subjects": "全部科目",
    "mode_label": "遇到已存在的 Markdown 文件时怎么处理",
    "mode_options": {
        "incremental": "增量导出（推荐）：只写新增或变化的文件",
        "overwrite": "覆盖重建：先清空导出目录再重新生成",
    },
    "info": (
        "这是私人 Markdown / Obsidian 导出，可以包含插问树、知识卡片、错因、复习计划、"
        "学习记录等个人学习资料；不会导出 API Key、密钥库或 API provider 敏感字段。"
    ),
    "button": "生成私人 Markdown 知识库",
    "success_template": "已生成/更新 {files_written} 个 Markdown 文件",
    "vault_caption": "可以直接用 Obsidian 打开上面的 user vault 目录。",
}


def get_markdown_export_copy() -> dict[str, object]:
    return MARKDOWN_EXPORT_COPY


def render() -> None:
    user = require_login()
    copy = get_markdown_export_copy()
    st.title(copy["title"])
    st.caption(copy["caption"])

    subjects = [
        row["subject"]
        for row in fetch_all(
            """
            SELECT DISTINCT subject
            FROM (
                SELECT subject FROM knowledge_cards WHERE user_id = ?
                UNION
                SELECT subject FROM ppt_decks WHERE user_id = ?
                UNION
                SELECT subject FROM mistakes WHERE user_id = ?
                UNION
                SELECT subject FROM study_sessions WHERE user_id = ?
            )
            WHERE subject IS NOT NULL AND TRIM(subject) != ''
            ORDER BY subject ASC
            """,
            (user.id, user.id, user.id, user.id),
        )
    ]
    subject_choice = st.selectbox(copy["subject_label"], [copy["all_subjects"], *subjects], key="markdown_export_subject")
    mode = st.radio(
        copy["mode_label"],
        ["incremental", "overwrite"],
        format_func=lambda item: copy["mode_options"][item],
        horizontal=True,
    )

    st.info(copy["info"])
    if st.button(copy["button"], type="primary"):
        result = export_obsidian_vault(
            user.id,
            subject=None if subject_choice == copy["all_subjects"] else subject_choice,
            mode=mode,
        )
        root = Path(result["root"])
        st.success(copy["success_template"].format(files_written=result["files_written"]))
        st.code(str(root), language="text")
        st.caption(copy["vault_caption"])
