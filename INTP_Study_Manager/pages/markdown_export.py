from __future__ import annotations

from pathlib import Path

import streamlit as st

from db import fetch_all
from services.auth_service import require_login
from services.markdown_export_service import export_obsidian_vault


def render() -> None:
    user = require_login()
    st.title("私人 Markdown / Obsidian 导出")
    st.caption("单向导出 SQLite 中的个人学习资料，适合用 Obsidian、VS Code、Typora 或 Git 备份阅读。")

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
    subject_choice = st.selectbox("导出范围", ["全部科目", *subjects], key="markdown_export_subject")
    mode = st.radio("导出模式", ["incremental", "overwrite"], format_func=lambda item: "增量导出" if item == "incremental" else "覆盖导出", horizontal=True)

    st.info("私人导出可以包含插问树、知识卡片、错因、复习计划和学习记录；不会导出 API Key、密钥库或 API provider 敏感字段。")
    if st.button("开始导出", type="primary"):
        result = export_obsidian_vault(
            user.id,
            subject=None if subject_choice == "全部科目" else subject_choice,
            mode=mode,
        )
        root = Path(result["root"])
        st.success(f"导出完成，写入 {result['files_written']} 个 Markdown 文件。")
        st.code(str(root), language="text")
        st.caption("可以直接用 Obsidian 打开上面的 user vault 目录。")
