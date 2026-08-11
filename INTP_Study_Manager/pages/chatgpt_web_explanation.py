from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from db import fetch_all
from services import chatgpt_explanation_result_service as result_service
from services import chatgpt_explanation_task_service as task_service
from services import chatgpt_inbox_service as inbox_service
from services.auth_service import require_login
from services.ppt_reader_state import LAST_READER_DECK_STATE_KEY
from services.ui_helpers import render_workbench_header, set_navigation_target


NAV_INTENT_KEY = "chatgpt_web_explanation_nav_intent"
DECK_STATE_KEY = "chatgpt_web_explanation_deck_id"
SUBJECT_STATE_KEY = "chatgpt_web_explanation_subject"
RANGE_MODE_STATE_KEY = "chatgpt_web_explanation_range_mode"
SECTION_STATE_KEY = "chatgpt_web_explanation_section_index"
RANGE_SPEC_STATE_KEY = "chatgpt_web_explanation_range_spec"

RANGE_LABELS = {
    "当前目录块": "section",
    "自定义页码": "custom",
    "全部 PPT": "all",
}

PRIVATE_DATA_LABELS = [
    "逐页插问和追问树",
    "知识卡片、错题与复习任务",
    "掌握度、学习会话和个人复盘",
    "停车场与每日复习记录",
    "API Provider、API Key、app_settings 和密钥库",
]


def render() -> None:
    user = require_login()
    render_workbench_header(
        "ChatGPT 网页讲解",
        "生成标准任务 ZIP，在网页版 ChatGPT 完成逐页精讲，再把结果文件安全导回当前 PPT。",
    )
    st.info(
        "这是文件交换桥接协议：不控制浏览器、不读取 Cookie、不抓取 ChatGPT 页面，也不要求 OpenAI API。"
    )
    with st.expander("直接模式与 fallback", expanded=False):
        st.markdown(
            """
**方式 A：ChatGPT MCP 直接模式**

- 在完成独立的 ChatGPT / MCP 连接层配置后，可按本地权限读取当前页并直接追加保存。
- 本地 stdio Server 正在运行，不等于网页版 ChatGPT 已完成连接。

**方式 B：文件桥接模式**

- 不依赖 MCP，继续使用 task ZIP / explanation_result.json / Inbox。
- 本页继续提供方式 B，作为没有 MCP write 能力时的 fallback。
            """
        )

    decks = _load_decks(user.id)
    intent = _consume_navigation_intent(user.id, decks)
    _render_task_creator(user.id, decks, intent)

    st.divider()
    _render_inbox(user.id)

    st.divider()
    _render_manual_upload(user.id)


def _load_decks(user_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT d.*, COUNT(s.id) AS actual_slide_count
        FROM ppt_decks d
        LEFT JOIN ppt_slides s
          ON s.user_id = d.user_id AND s.deck_id = d.id
        WHERE d.user_id = ?
        GROUP BY d.id
        ORDER BY d.subject ASC, d.created_at DESC, d.id DESC
        """,
        (int(user_id),),
    )


def _consume_navigation_intent(user_id: int, decks: list[dict[str, Any]]) -> dict[str, Any]:
    raw = st.session_state.pop(NAV_INTENT_KEY, None)
    if not isinstance(raw, dict):
        return {}
    deck_by_id = {int(deck["id"]): deck for deck in decks}
    try:
        deck_id = int(raw.get("deck_id") or 0)
    except (TypeError, ValueError):
        return {}
    deck = deck_by_id.get(deck_id)
    if not deck or int(deck.get("user_id") or 0) != int(user_id):
        return {}
    intent = dict(raw)
    intent["deck_id"] = deck_id
    st.session_state[SUBJECT_STATE_KEY] = deck.get("subject") or "未分类"
    st.session_state[DECK_STATE_KEY] = deck_id
    return intent


def _render_task_creator(user_id: int, decks: list[dict[str, Any]], intent: dict[str, Any]) -> None:
    st.subheader("A. 创建 ChatGPT 讲解任务")
    if not decks:
        st.warning("还没有可生成任务的 PPT / PDF，请先到 PPT 学习工作台导入资料。")
        return

    subjects = sorted({str(deck.get("subject") or "未分类") for deck in decks})
    if st.session_state.get(SUBJECT_STATE_KEY) not in subjects:
        st.session_state[SUBJECT_STATE_KEY] = subjects[0]
    selected_subject = st.selectbox("科目", subjects, key=SUBJECT_STATE_KEY)
    subject_decks = [deck for deck in decks if str(deck.get("subject") or "未分类") == selected_subject]
    deck_by_id = {int(deck["id"]): deck for deck in subject_decks}
    if st.session_state.get(DECK_STATE_KEY) not in deck_by_id:
        st.session_state[DECK_STATE_KEY] = next(iter(deck_by_id))
    deck_id = int(
        st.selectbox(
            "PPT / PDF",
            list(deck_by_id),
            key=DECK_STATE_KEY,
            format_func=lambda value: _deck_label(deck_by_id[int(value)]),
        )
    )

    sections = _load_sections(user_id, deck_id)
    _apply_intent_scope(intent, deck_id, sections)
    scope_options = list(RANGE_LABELS)
    if st.session_state.get(RANGE_MODE_STATE_KEY) not in scope_options:
        st.session_state[RANGE_MODE_STATE_KEY] = "当前目录块" if sections else "自定义页码"
    range_label = st.radio(
        "任务范围",
        scope_options,
        horizontal=True,
        key=RANGE_MODE_STATE_KEY,
    )
    range_mode = RANGE_LABELS[range_label]
    section_index: int | None = None
    slide_numbers: list[int] | None = None
    range_error = ""

    if range_mode == "section":
        if not sections:
            range_error = "当前 PPT 还没有目录块，请改用自定义页码或全部 PPT。"
            st.warning(range_error)
        else:
            section_ids = [int(section["section_index"]) for section in sections]
            if st.session_state.get(SECTION_STATE_KEY) not in section_ids:
                st.session_state[SECTION_STATE_KEY] = section_ids[0]
            section_index = int(
                st.selectbox(
                    "当前目录块",
                    section_ids,
                    key=SECTION_STATE_KEY,
                    format_func=lambda value: _section_label(sections, int(value)),
                )
            )
    elif range_mode == "custom":
        if not str(st.session_state.get(RANGE_SPEC_STATE_KEY) or "").strip():
            st.session_state[RANGE_SPEC_STATE_KEY] = "1-5"
        range_spec = st.text_input(
            "自定义页码",
            key=RANGE_SPEC_STATE_KEY,
            help="支持 1-5、1,3,8-10 这类写法。",
        )
        try:
            slide_numbers = task_service.parse_slide_number_spec(range_spec)
        except ValueError as exc:
            range_error = str(exc)
            st.warning(range_error)

    include_images = st.checkbox(
        "包含页面图片",
        value=False,
        help="默认关闭。只在公式、图表或版式对讲解很重要时开启。",
    )
    include_existing = st.checkbox(
        "包含现有 AI 逐页讲解作为参考",
        value=False,
        help="默认关闭。开启后只加入所选页面当前最新的一版讲解。",
    )

    with st.expander("隐私边界：不会进入任务包的内容", expanded=False):
        st.write("任务包按允许字段构造，不是完整个人学习数据导出：")
        for label in PRIVATE_DATA_LABELS:
            st.write(f"- {label}")

    plan = None
    if not range_error:
        try:
            plan = task_service.plan_task_packages(
                user_id,
                deck_id,
                range_mode=range_mode,
                section_index=section_index,
                slide_numbers=slide_numbers,
            )
        except ValueError as exc:
            range_error = str(exc)
            st.warning(range_error)

    page_count = int(plan.get("slide_count") or 0) if plan else 0
    package_count = int(plan.get("package_count") or 0) if plan else 0
    count_col, package_col = st.columns(2)
    count_col.metric("预计页数", page_count)
    package_col.metric("预计任务包数", package_count)
    if package_count > 1:
        st.caption("大 PPT 会优先按目录块拆包；过大的目录块继续按每包最多 20 页拆分。")

    if st.button(
        "生成 ChatGPT 任务包",
        type="primary",
        disabled=plan is None or page_count <= 0,
        key="chatgpt_web_create_tasks",
    ):
        try:
            created = task_service.create_task_packages(
                user_id,
                deck_id,
                range_mode=range_mode,
                section_index=section_index,
                slide_numbers=slide_numbers,
                include_images=include_images,
                include_existing_explanations=include_existing,
            )
        except Exception as exc:
            st.error(f"任务包生成失败：{exc}")
        else:
            st.success(
                f"已生成 {created['package_count']} 个任务包，共 {created['slide_count']} 页。"
            )

    _render_task_downloads(user_id)


def _apply_intent_scope(intent: dict[str, Any], deck_id: int, sections: list[dict[str, Any]]) -> None:
    if not intent or int(intent.get("deck_id") or 0) != int(deck_id):
        return
    try:
        slide_number = int(intent.get("slide_number") or 0)
    except (TypeError, ValueError):
        slide_number = 0
    requested_section = intent.get("section_index")
    valid_section = next(
        (
            section
            for section in sections
            if int(section["section_index"]) == int(requested_section or 0)
            and int(section["start_slide"]) <= slide_number <= int(section["end_slide"])
        ),
        None,
    )
    if valid_section:
        st.session_state[RANGE_MODE_STATE_KEY] = "当前目录块"
        st.session_state[SECTION_STATE_KEY] = int(valid_section["section_index"])
    elif slide_number > 0:
        st.session_state[RANGE_MODE_STATE_KEY] = "自定义页码"
        st.session_state[RANGE_SPEC_STATE_KEY] = str(slide_number)


def _render_task_downloads(user_id: int) -> None:
    try:
        tasks = task_service.list_tasks(user_id)
    except Exception as exc:
        st.warning(f"暂时无法读取任务记录：{exc}")
        return
    downloadable = [task for task in tasks if Path(str(task.get("package_path") or "")).is_file()]
    if not downloadable:
        return

    st.markdown("#### 已生成的任务包")
    for task in downloadable[:20]:
        path = Path(task["package_path"])
        slide_count = len(task.get("requested_slides") or [])
        cols = st.columns([4, 1])
        cols[0].caption(
            f"{task['task_id']} · {slide_count} 页 · 状态 {task.get('status') or 'waiting_result'}"
        )
        cols[1].download_button(
            "下载任务 ZIP",
            data=path.read_bytes(),
            file_name=path.name,
            mime="application/zip",
            key=f"download_{task['task_id']}",
        )

    st.markdown(
        """
1. 下载任务 ZIP。
2. 把整个 ZIP 上传到网页版 ChatGPT。
3. 输入：`按任务包 instructions.md 的要求生成逐页讲解，并生成 explanation_result.json 给我下载。`
4. 把下载目录设为下方 Inbox，或将结果文件上传到页面底部。
        """
    )


def _render_inbox(user_id: int) -> None:
    st.subheader("B. Inbox 自动发现")
    inbox_path = inbox_service.inbox_directory()
    st.caption(f"浏览器下载目录可设置为：{inbox_path}")
    mode = st.radio(
        "检测到结果后",
        ["等待确认", "完整校验通过后自动导入"],
        index=0,
        horizontal=True,
        key="chatgpt_web_auto_import_mode",
    )
    auto_import = mode == "完整校验通过后自动导入"
    st.button("立即扫描 Inbox", key="chatgpt_web_scan_inbox")
    try:
        items = inbox_service.scan(user_id, auto_import=auto_import)
    except Exception as exc:
        st.error(f"Inbox 扫描失败：{exc}")
        return

    try:
        tasks = task_service.list_tasks(user_id)
    except Exception as exc:
        st.warning(f"暂时无法读取等待任务：{exc}")
        tasks = []
    waiting = [
        task
        for task in tasks
        if task.get("status") in {"created", "waiting_result", "result_detected", "partial"}
    ]
    st.metric("等待结果的任务", len(waiting))
    if not items:
        st.info("Inbox 中暂未检测到可处理的 explanation_result.json。")
        return
    for item in items:
        _render_inbox_item(user_id, item)


def _render_inbox_item(user_id: int, item: dict[str, Any]) -> None:
    path = Path(str(item.get("path") or ""))
    status = str(item.get("status") or "invalid")
    with st.container(border=True):
        st.markdown(f"**{path.name or '结果文件'}**")
        report = item.get("report") or {}
        if status == "waiting_stable":
            st.info("文件仍在下载或刚刚变化，本轮暂不读取。")
            return
        if status == "already_imported":
            if _same_path(report.get("existing_source_path"), path):
                st.warning("讲解已导入，但原始结果文件仍在 Inbox，尚未完成归档。")
                if st.button("重试归档", key=f"retry_archive_{path.name}"):
                    try:
                        outcome = inbox_service.import_inbox_result(user_id, path)
                    except Exception as exc:
                        st.error(f"归档重试失败：{exc}")
                    else:
                        _render_import_success(outcome)
            else:
                st.info("已导入，跳过。")
            return
        if status == "imported":
            outcome = item.get("import") if isinstance(item.get("import"), dict) else {}
            if outcome.get("archive_status") == "archived":
                st.success("完整校验通过，已自动导入并归档。")
            else:
                st.warning("讲解已自动导入，但原始结果文件尚未成功归档。")
                if outcome.get("archive_error"):
                    st.error(str(outcome["archive_error"]))
            return
        if report.get("task_exists"):
            st.caption(
                f"PPT：{report.get('deck_title') or report.get('deck_id') or '未知'} · "
                f"Task：{report.get('task_id') or '未知'}"
            )
        _render_validation_report(report)
        if status not in {"ready", "partial"} or not report.get("hard_valid"):
            return
        label = "导入" if report.get("complete") else f"导入有效 {report.get('valid_count') or 0} 页"
        actions = st.columns(2)
        if actions[0].button(label, key=f"import_inbox_{path.name}"):
            try:
                outcome = inbox_service.import_inbox_result(
                    user_id,
                    path,
                    allow_partial=not bool(report.get("complete")),
                )
            except Exception as exc:
                st.error(f"导入失败：{exc}")
            else:
                _render_import_success(outcome)
        if actions[1].button("暂不导入", key=f"defer_inbox_{path.name}"):
            st.info("结果仍保留在 Inbox，稍后可重新扫描并导入。")


def _render_manual_upload(user_id: int) -> None:
    st.subheader("C. 手动上传 explanation_result.json")
    st.caption("这是上传文件，不需要复制粘贴任何逐页讲解文字。")
    uploaded = st.file_uploader(
        "上传 explanation_result.json",
        type=["json"],
        key="chatgpt_web_manual_result",
    )
    if uploaded is None:
        return
    raw = uploaded.getvalue()
    report = result_service.preview_result(user_id, raw)
    _render_validation_report(report)
    if report.get("duplicate"):
        st.info("已导入，跳过。")
        return
    if not report.get("hard_valid") or int(report.get("valid_count") or 0) <= 0:
        return
    label = "确认导入" if report.get("complete") else f"导入有效 {report.get('valid_count')} 页"
    if st.button(label, type="primary", key="chatgpt_web_manual_import"):
        try:
            source = inbox_service.save_uploaded_result(raw, filename=uploaded.name)
            outcome = inbox_service.import_inbox_result(
                user_id,
                source,
                allow_partial=not bool(report.get("complete")),
            )
        except Exception as exc:
            st.error(f"导入失败：{exc}")
        else:
            _render_import_success(outcome)


def _render_validation_report(report: dict[str, Any]) -> None:
    requested = int(report.get("requested_count") or 0)
    valid = int(report.get("valid_count") or 0)
    unknown = len(report.get("unknown_slide_ids") or [])
    missing = len(report.get("missing_slide_ids") or [])
    cols = st.columns(4)
    cols[0].metric("匹配", f"{valid} / {requested}")
    cols[1].metric("未知页", unknown)
    cols[2].metric("缺失页", missing)
    cols[3].metric("Fingerprint", "通过" if report.get("fingerprint_ok") else "未通过")

    if report.get("duplicate"):
        st.info("已导入，跳过。")
    elif report.get("hard_valid") and report.get("complete"):
        st.success("状态：可完整导入")
    elif report.get("hard_valid"):
        st.warning(f"部分结果：{valid} / {requested}，只能人工确认后导入有效页。")
    else:
        st.error("状态：不可导入")
    for error in report.get("errors") or []:
        st.error(str(error))
    for warning in report.get("warnings") or []:
        st.warning(str(warning))

    payload = report.get("payload")
    if isinstance(payload, dict) and (
        report.get("hard_valid") or report.get("duplicate_payload_matches") is True
    ):
        with st.expander("预览结果", expanded=False):
            st.json(
                {
                    key: value
                    for key, value in payload.items()
                    if key != "slides"
                }
            )
            for slide in (payload.get("slides") or [])[:50]:
                st.markdown(
                    f"**第 {slide.get('slide_number')} 页 · slide_id={slide.get('slide_id')}**"
                )
                st.markdown(str(slide.get("explanation") or ""))


def _render_import_success(outcome: dict[str, Any]) -> None:
    if outcome.get("status") == "skipped":
        if outcome.get("archive_status") == "archived":
            st.success("已导入过，本次未重复写库；原始结果文件已完成归档。")
        elif outcome.get("archive_status") == "failed":
            st.warning("已导入过，本次未重复写库，但原始结果文件仍未成功归档。")
            if outcome.get("archive_error"):
                st.error(str(outcome["archive_error"]))
        else:
            st.info("已导入，跳过。")
        return
    imported_message = (
        f"导入完成：新增 {outcome.get('imported_count') or 0} 页 ChatGPT Web 讲解，旧讲解仍保留。"
    )
    if outcome.get("archive_status") == "archived":
        st.success(imported_message)
    else:
        st.warning(imported_message + " 原始结果文件尚未成功归档，已保留以便重试。")
        if outcome.get("archive_error"):
            st.error(str(outcome["archive_error"]))
    deck_id = int(outcome.get("deck_id") or 0)
    if st.button("返回 PPT 学习工作台", key=f"return_to_ppt_{outcome.get('result_id')}"):
        if deck_id:
            st.session_state[LAST_READER_DECK_STATE_KEY] = deck_id
        set_navigation_target("materials", "ppt_tutor")
        st.rerun()


def _load_sections(user_id: int, deck_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT *
        FROM ppt_sections
        WHERE user_id = ? AND deck_id = ?
        ORDER BY section_index ASC
        """,
        (int(user_id), int(deck_id)),
    )


def _deck_label(deck: dict[str, Any]) -> str:
    title = deck.get("title") or deck.get("filename") or "未命名 PPT/PDF"
    count = int(deck.get("actual_slide_count") or deck.get("slide_count") or 0)
    return f"#{deck['id']} {title}（{count} 页）"


def _section_label(sections: list[dict[str, Any]], section_index: int) -> str:
    section = next(item for item in sections if int(item["section_index"]) == int(section_index))
    return (
        f"{section['section_index']}. {section.get('title') or '未命名目录块'} "
        f"（第 {section['start_slide']}-{section['end_slide']} 页）"
    )


def _same_path(left: object, right: Path) -> bool:
    if not str(left or "").strip():
        return False
    try:
        return Path(str(left)).resolve(strict=False) == right.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return False
