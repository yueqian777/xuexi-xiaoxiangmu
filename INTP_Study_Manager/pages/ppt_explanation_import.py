from __future__ import annotations

import streamlit as st

from services.auth_service import require_login
from services.ppt_explanation_import_service import import_share_package, preview_share_package


def render() -> None:
    user = require_login()
    st.title("PPT 讲解包导入")
    st.caption("本地 ZIP 导入，只接受 privacy_mode=public_ppt_explanation_only 的公开 PPT 讲解分享包。")

    uploaded = st.file_uploader("上传 ZIP", type=["zip"])
    if uploaded is None:
        return

    try:
        preview = preview_share_package(user.id, uploaded)
    except Exception as exc:
        st.error(f"无法读取分享包：{exc}")
        return

    st.subheader("包信息")
    cols = st.columns(3)
    cols[0].metric("Subject", preview.get("subject") or "未分类")
    cols[1].metric("Slides", preview.get("slide_count") or 0)
    cols[2].metric("Original", "yes" if preview.get("has_original") else "no")
    st.write(
        {
            "package_id": preview["package_id"],
            "package_type": preview["package_type"],
            "version": preview["version"],
            "privacy_mode": preview["privacy_mode"],
            "title": preview["deck_title"],
            "already_imported": preview["already_imported"],
        }
    )

    duplicate_policy = "copy"
    if preview["already_imported"]:
        duplicate_policy = st.radio("重复导入处理", ["skip", "copy"], format_func=lambda item: "跳过" if item == "skip" else "导入为副本", horizontal=True)

    if st.button("确认导入", type="primary"):
        try:
            uploaded.seek(0)
            result = import_share_package(user.id, uploaded, duplicate_policy=duplicate_policy)
        except Exception as exc:
            st.error(f"导入失败：{exc}")
            return
        if result["status"] == "skipped":
            st.info("该 package_id 已导入，已按你的选择跳过。")
        else:
            st.success(f"导入完成，新 deck_id：{result['deck_id']}。导入后可继续创建你自己的插问、知识卡片和复习任务。")
