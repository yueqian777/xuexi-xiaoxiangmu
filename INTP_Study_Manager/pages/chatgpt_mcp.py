from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

from services import active_learning_context_service as active_context_service
from services import mcp_audit_service as audit_service
from services import mcp_permission_service as permission_service
from services import mcp_runtime_status_service as runtime_status_service
from services.auth_service import require_login
from services.ui_helpers import render_workbench_header


APP_ROOT = Path(__file__).resolve().parents[1]

PERMISSION_LABELS = {
    "read_current_context": "当前学习上下文",
    "read_ppt": "PPT 内容",
    "read_question_tree": "插问树",
    "read_knowledge_cards": "知识卡片",
    "read_reviews": "复习历史",
    "write_slide_explanation": "保存新的逐页讲解",
    "write_slide_question": "新建插问",
    "write_knowledge_card": "转知识卡片",
    "write_review": "创建或提交复习任务",
}
READ_PERMISSION_KEYS = tuple(key for key in PERMISSION_LABELS if key.startswith("read_"))
WRITE_PERMISSION_KEYS = tuple(key for key in PERMISSION_LABELS if key.startswith("write_"))

STATUS_LABELS = {
    "running": "运行中",
    "stopped": "已停止",
    "stale": "未运行（记录中的 PID 已失效）",
    "unverified": "未运行（进程身份无法验证）",
    "never_started": "未运行",
}


def render() -> None:
    user = require_login()
    user_id = int(user.id)
    render_workbench_header(
        "ChatGPT / MCP",
        "查看本机 Study MCP 状态、Active Context、细粒度权限与最近审计记录。",
    )
    st.info(
        "这里管理的是本地 stdio MCP。它不会把 SQLite、Streamlit 或无鉴权 HTTP 接口暴露到公网；"
        "本地进程运行也不代表网页版 ChatGPT 已完成连接。"
    )

    _render_runtime_status(user_id)
    st.divider()
    _render_active_context(user_id)
    st.divider()
    _render_permission_form(user_id)
    st.divider()
    _render_recent_audit(user_id)
    st.divider()
    _render_developer_tools(user_id)


def _render_runtime_status(user_id: int) -> None:
    st.subheader("MCP Server 状态")
    try:
        status = runtime_status_service.get_runtime_status(user_id)
    except Exception:
        st.error("暂时无法读取本地 MCP 运行状态。")
        return

    state = str(status.get("state") or "never_started")
    status_col, transport_col, pid_col = st.columns(3)
    status_col.metric("状态", STATUS_LABELS.get(state, "未知"))
    transport_col.metric("Transport", status.get("transport") or "stdio（尚未启动）")
    pid_col.metric("PID", status.get("pid") or "—")
    if status.get("started_at"):
        st.caption(f"最近启动：{status['started_at']}")
    if state == "stale":
        st.warning("状态记录存在，但 PID 已不再运行。下次启动 stdio MCP 时会刷新该记录。")
    elif state == "unverified":
        st.warning("PID 仍存在，但无法验证进程创建身份；为避免 PID 复用误报，不标记为运行中。")
    elif state == "stopped" and status.get("stopped_at"):
        st.caption(f"最近停止：{status['stopped_at']}")
    st.caption("启动和停止由独立终端进程负责；本页不会在 Streamlit 内托管 MCP 子进程。")


def _render_active_context(user_id: int) -> None:
    st.subheader("当前 Active Context")
    try:
        context = active_context_service.get_active_context(user_id)
    except Exception:
        st.error("暂时无法读取当前学习上下文。")
        return
    if not context.get("active"):
        st.info("当前没有 Active Context。进入 PPT 学习工作台并选择页面后会建立上下文。")
        return
    summary = st.columns(4)
    summary[0].metric("科目", context.get("subject") or "—")
    summary[1].metric("Deck", context.get("deck_title") or context.get("deck_id") or "—")
    summary[2].metric("页码", context.get("slide_number") or "—")
    summary[3].metric("Slide ID", context.get("slide_id") or "—")
    with st.expander("查看结构化上下文", expanded=False):
        st.json(context)


def _render_permission_form(user_id: int) -> None:
    st.subheader("ChatGPT / MCP 权限")
    st.caption("权限在本机、按当前 user_id 持久化；每次 Tool 调用都会再次检查。")
    try:
        permissions = permission_service.get_permissions(user_id)
    except Exception:
        st.error("暂时无法读取 MCP 权限。")
        return

    with st.form("mcp_permissions"):
        read_col, write_col = st.columns(2)
        updates: dict[str, bool] = {}
        with read_col:
            st.markdown("#### 读取权限")
            for key in READ_PERMISSION_KEYS:
                updates[key] = st.checkbox(
                    PERMISSION_LABELS[key],
                    value=bool(permissions[key]),
                    key=f"mcp_permission_{user_id}_{key}",
                )
        with write_col:
            st.markdown("#### 写入权限")
            for key in WRITE_PERMISSION_KEYS:
                updates[key] = st.checkbox(
                    PERMISSION_LABELS[key],
                    value=bool(permissions[key]),
                    key=f"mcp_permission_{user_id}_{key}",
                )
        submitted = st.form_submit_button("保存 MCP 权限", type="primary")

    st.warning("危险操作：第一版不提供删除接口，也没有任何 delete Tool。")
    if not submitted:
        return
    try:
        permission_service.set_permissions(user_id, updates)
    except Exception:
        st.error("MCP 权限保存失败。")
        return
    st.success("MCP 权限已保存。后续 Tool 调用立即按新值检查。")


def _render_recent_audit(user_id: int) -> None:
    st.subheader("最近 MCP 操作")
    st.caption("只显示请求与对象元数据；审计不保存 prompt、逐页讲解正文、API Key 或 secret。")
    try:
        logs = audit_service.list_recent_audit_logs(user_id, limit=50)
    except Exception:
        st.error("暂时无法读取 MCP 审计记录。")
        return
    if not logs:
        st.info("当前用户还没有 MCP 操作记录。")
        return

    rows = [_audit_display_row(item) for item in logs]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _audit_display_row(item: dict[str, Any]) -> dict[str, Any]:
    target_type = str(item.get("target_type") or "")
    target_id = str(item.get("target_id") or "")
    target = " / ".join(value for value in (target_type, target_id) if value) or "—"
    permission_result = str(item.get("permission_result") or "")
    success = bool(item.get("success"))
    if permission_result == "permission_denied":
        status = "权限拒绝"
    else:
        status = "成功" if success else "失败"
    return {
        "时间": item.get("created_at") or "",
        "Tool": item.get("tool_name") or "",
        "读/写": item.get("operation_type") or "",
        "对象": target,
        "状态": status,
        "来源": "stdio",
        "请求标识": item.get("request_id") or "",
        "摘要": item.get("summary") or "",
    }


def _render_developer_tools(user_id: int) -> None:
    with st.expander("开发与本地测试", expanded=False):
        st.markdown("#### 复制 MCP 配置")
        st.caption("代码框右上角可复制。配置仅启动本地 stdio 进程，不含 token 或 API Key。")
        st.code(_stdio_config_text(user_id), language="json")
        st.code(
            f'"{sys.executable}" -m study_mcp.server --transport stdio --user-id {user_id}',
            language="powershell",
        )
        st.caption("以下按钮只读测试本地 domain service；不会写业务数据，也不代表 ChatGPT Web 已连接。")
        context_col, slide_col = st.columns(2)
        if context_col.button("测试 get_current_context", key="mcp_test_current_context"):
            try:
                st.json(active_context_service.get_active_context(user_id))
            except Exception:
                st.error("get_current_context 本地测试失败。")
        if slide_col.button("测试 get_current_slide", key="mcp_test_current_slide"):
            try:
                from services import study_mcp_domain_service

                st.json(study_mcp_domain_service.get_current_slide(user_id))
            except Exception as exc:
                code = str(getattr(exc, "code", "local_test_failed"))
                st.error(f"get_current_slide 本地测试失败：{code}")


def _stdio_config_text(user_id: int) -> str:
    config = {
        "mcpServers": {
            "intp-study-manager": {
                "command": sys.executable,
                "args": [
                    "-m",
                    "study_mcp.server",
                    "--transport",
                    "stdio",
                    "--user-id",
                    str(int(user_id)),
                ],
                "cwd": str(APP_ROOT),
            }
        }
    }
    return json.dumps(config, ensure_ascii=False, indent=2)
