from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import streamlit as st

from db import init_db
from pages import (
    api_settings,
    dashboard,
    knowledge_cards,
    mainline_branches,
    mistakes,
    markdown_export,
    parking_lot,
    ppt_explanation_export,
    ppt_explanation_import,
    ppt_management,
    ppt_tutor,
    quiz_prompts,
    reminders,
    reviews,
    study_sessions,
)
from services.ai_service import ensure_default_api_providers
from services.auth_service import require_login

APP_ROOT = Path(__file__).resolve().parent
ENTER_SUBMIT_SHORTCUT_SCRIPT = (
    APP_ROOT / "components" / "enter_submit_shortcut.js"
).read_text(encoding="utf-8")

@dataclass(frozen=True)
class NavSection:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class NavEntry:
    id: str
    label: str
    section_id: str
    render: Callable[[], None]
    description: str


NAV_SECTIONS = (
    NavSection("today", "今日工作台", "先看今天该做什么，再进入具体工作区。"),
    NavSection("materials", "资料学习", "围绕 PPT / PDF 资料完成阅读、讲解、插问和分享。"),
    NavSection("knowledge", "知识沉淀", "把学习记录、知识点、主线和临时问题沉淀下来。"),
    NavSection("review", "复习纠错", "闭卷回忆、间隔复习和错因分析集中处理。"),
    NavSection("maintenance", "系统维护", "API、导出、提醒等低频配置统一放在这里。"),
)

NAV_ENTRIES = (
    NavEntry("dashboard", "今日工作台", "today", dashboard.render, "今日复习、继续学习和卡点概览。"),
    NavEntry("ppt_tutor", "PPT 学习工作台", "materials", ppt_tutor.render, "阅读、逐页讲解、插问和学习沉淀。"),
    NavEntry("ppt_management", "PPT / 插问管理", "materials", ppt_management.render, "资料分类、排序、状态和删除。"),
    NavEntry("ppt_explanation_import", "导入讲解包", "materials", ppt_explanation_import.render, "导入别人分享的 PPT 讲解包。"),
    NavEntry("ppt_explanation_export", "分享讲解包", "materials", ppt_explanation_export.render, "导出可分享的 PPT 讲解资料。"),
    NavEntry("study_sessions", "学习登记", "knowledge", study_sessions.render, "记录当天学习主题、卡点和掌握度。"),
    NavEntry("knowledge_cards", "知识点卡片", "knowledge", knowledge_cards.render, "浏览、编辑和关联核心知识点。"),
    NavEntry("mainline_branches", "主线与插问", "knowledge", mainline_branches.render, "整理主线锚点和插问脉络。"),
    NavEntry("parking_lot", "探索停车场", "knowledge", parking_lot.render, "暂存不打断主线的扩展问题。"),
    NavEntry("reviews", "复习计划", "review", reviews.render, "处理 1-3-7-14 间隔复习任务。"),
    NavEntry("quiz_prompts", "闭卷测试 Prompt", "review", quiz_prompts.render, "生成闭卷回忆和每日复盘 Prompt。"),
    NavEntry("mistakes", "错因本", "review", mistakes.render, "记录错题、错因和高频问题。"),
    NavEntry("api_settings", "API 接入设置", "maintenance", api_settings.render, "模型接口、密钥库、测试和高级参数。"),
    NavEntry("markdown_export", "Markdown / Obsidian 导出", "maintenance", markdown_export.render, "导出私人学习资料。"),
    NavEntry("reminders", "每日复盘提醒", "maintenance", reminders.render, "配置本地 Windows 复盘提醒。"),
)

PAGES = {entry.id: entry.render for entry in NAV_ENTRIES}
LEGACY_PAGE_IDS = {
    "首页 Dashboard": "dashboard",
    "PPT 逐页讲解": "ppt_tutor",
    "PPT 与插问管理": "ppt_management",
    "每日复盘提醒": "reminders",
    "API 接入设置": "api_settings",
    "学习登记": "study_sessions",
    "知识点卡片": "knowledge_cards",
    "闭卷测试 Prompt": "quiz_prompts",
    "复习计划": "reviews",
    "探索停车场": "parking_lot",
    "主线与插问": "mainline_branches",
    "错因本": "mistakes",
    "私人 Markdown / Obsidian 导出": "markdown_export",
    "PPT 讲解分享包": "ppt_explanation_export",
    "PPT 讲解包导入": "ppt_explanation_import",
}

DEFAULT_SECTION_ID = "today"
DEFAULT_PAGE_ID = "dashboard"
SELECTED_SECTION_STATE_KEY = "app_selected_section_id"
SELECTED_PAGE_STATE_KEY = "app_selected_page_id"
PAGE_SECTION_SYNC_STATE_KEY = "app_selected_page_section_id"

ACTIVE_PAGE_STATE_KEY = "app_active_page_name"
PAGE_JUST_ENTERED_STATE_KEY = "app_page_just_entered"


def _normalize_page_id(page_id_or_label: str | None) -> str:
    if page_id_or_label in PAGES:
        return str(page_id_or_label)
    if page_id_or_label in LEGACY_PAGE_IDS:
        return LEGACY_PAGE_IDS[str(page_id_or_label)]
    return DEFAULT_PAGE_ID


def _entry_by_id(page_id_or_label: str | None) -> NavEntry:
    page_id = _normalize_page_id(page_id_or_label)
    for entry in NAV_ENTRIES:
        if entry.id == page_id:
            return entry
    return NAV_ENTRIES[0]


def _section_by_id(section_id: str | None) -> NavSection:
    for section in NAV_SECTIONS:
        if section.id == section_id:
            return section
    return NAV_SECTIONS[0]


def _entries_for_section(section_id: str | None) -> list[NavEntry]:
    normalized_section = _section_by_id(section_id).id
    return [entry for entry in NAV_ENTRIES if entry.section_id == normalized_section]


def _mark_active_page(page_id_or_label: str, state: dict | None = None) -> bool:
    state = st.session_state if state is None else state
    page_id = _normalize_page_id(page_id_or_label)
    previous_page = state.get(ACTIVE_PAGE_STATE_KEY)
    previous_page_id = _normalize_page_id(previous_page)
    just_entered = previous_page_id != page_id
    state[ACTIVE_PAGE_STATE_KEY] = page_id
    state[PAGE_JUST_ENTERED_STATE_KEY] = just_entered
    return just_entered


def _render_sidebar_navigation() -> NavEntry:
    state = st.session_state
    current_entry = _entry_by_id(
        state.get(SELECTED_PAGE_STATE_KEY) or state.get(ACTIVE_PAGE_STATE_KEY)
    )
    section_ids = [section.id for section in NAV_SECTIONS]
    if state.get(SELECTED_SECTION_STATE_KEY) not in section_ids:
        state[SELECTED_SECTION_STATE_KEY] = current_entry.section_id

    st.sidebar.title("INTP Study Manager")
    st.sidebar.caption("问题驱动 · 闭卷回忆 · 错因分析 · 间隔复习")
    section_id = st.sidebar.radio(
        "学习流程",
        section_ids,
        key=SELECTED_SECTION_STATE_KEY,
        format_func=lambda item: _section_by_id(item).label,
    )
    section = _section_by_id(section_id)
    st.sidebar.caption(section.description)

    entries = _entries_for_section(section_id)
    entry_ids = [entry.id for entry in entries]
    if (
        state.get(PAGE_SECTION_SYNC_STATE_KEY) != section_id
        or _normalize_page_id(state.get(SELECTED_PAGE_STATE_KEY)) not in entry_ids
    ):
        state[SELECTED_PAGE_STATE_KEY] = entry_ids[0]
        state[PAGE_SECTION_SYNC_STATE_KEY] = section_id

    page_id = st.sidebar.radio(
        "功能入口",
        entry_ids,
        key=SELECTED_PAGE_STATE_KEY,
        format_func=lambda item: _entry_by_id(item).label,
    )
    entry = _entry_by_id(page_id)
    st.sidebar.caption(entry.description)
    st.sidebar.divider()
    st.sidebar.markdown("**70% 原则**")
    st.sidebar.caption("掌握度达到 70% 可前进，低于 70% 自动进入重点关注。")
    return entry


def _install_browser_dom_guard() -> None:
    st.iframe(
        """
        <script>
        (() => {
          let rootWindow;
          try {
            rootWindow = window.parent || window;
            void rootWindow.document;
          } catch {
            rootWindow = window;
          }
          const shouldInstallCopyGuard = !rootWindow.__intpCopyShortcutGuardInstalled;
          rootWindow.__intpCopyShortcutGuardInstalled = true;

          try {
            const doc = rootWindow.document;
            doc.documentElement.setAttribute('translate', 'no');
            doc.documentElement.classList.add('notranslate');
            doc.body?.setAttribute('translate', 'no');
            doc.body?.classList.add('notranslate');
            if (!doc.querySelector('meta[name="google"][content="notranslate"]')) {
              const meta = doc.createElement('meta');
              meta.setAttribute('name', 'google');
              meta.setAttribute('content', 'notranslate');
              doc.head?.appendChild(meta);
            }
          } catch {}

          if (!rootWindow.__intpSafeDomPatchInstalled && rootWindow.Node?.prototype) {
            rootWindow.__intpSafeDomPatchInstalled = true;
            const originalRemoveChild = rootWindow.Node.prototype.removeChild;
            const originalInsertBefore = rootWindow.Node.prototype.insertBefore;

            rootWindow.Node.prototype.removeChild = function(child) {
              if (child && child.parentNode !== this) {
                return child.parentNode ? originalRemoveChild.call(child.parentNode, child) : child;
              }
              return originalRemoveChild.call(this, child);
            };

            rootWindow.Node.prototype.insertBefore = function(newNode, referenceNode) {
              if (referenceNode && referenceNode.parentNode !== this) {
                return this.appendChild(newNode);
              }
              return originalInsertBefore.call(this, newNode, referenceNode);
            };
          }

          const isCopyShortcut = (event) =>
            (event.ctrlKey || event.metaKey) &&
            !event.altKey &&
            String(event.key || '').toLowerCase() === 'c';

          const stopStreamlitCacheShortcut = (event) => {
            if (!isCopyShortcut(event)) return;
            event.stopPropagation();
            if (typeof event.stopImmediatePropagation === 'function') {
              event.stopImmediatePropagation();
            }
          };

          if (shouldInstallCopyGuard) {
            rootWindow.addEventListener('keydown', stopStreamlitCacheShortcut, true);
            rootWindow.document.addEventListener('keydown', stopStreamlitCacheShortcut, true);
          }
        })();
        </script>
        <script>
        """
        + ENTER_SUBMIT_SHORTCUT_SCRIPT
        + """
        </script>
        """,
        height=1,
        width=1,
    )


def main() -> None:
    st.set_page_config(
        page_title="INTP Study Manager",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _install_browser_dom_guard()
    init_db()
    user = require_login()
    user_id = user.id
    ensure_default_api_providers(user_id=user_id)

    entry = _render_sidebar_navigation()
    _mark_active_page(entry.id)
    entry.render()


if __name__ == "__main__":
    main()
