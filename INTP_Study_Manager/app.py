from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from db import init_db
from pages import (
    api_settings,
    dashboard,
    knowledge_cards,
    mainline_branches,
    mistakes,
    parking_lot,
    ppt_tutor,
    quiz_prompts,
    reviews,
    study_sessions,
)
from services.ai_service import ensure_default_api_providers

PAGES = {
    "首页 Dashboard": dashboard.render,
    "PPT 逐页讲解": ppt_tutor.render,
    "API 接入设置": api_settings.render,
    "学习登记": study_sessions.render,
    "知识点卡片": knowledge_cards.render,
    "闭卷测试 Prompt": quiz_prompts.render,
    "复习计划": reviews.render,
    "探索停车场": parking_lot.render,
    "主线与插问": mainline_branches.render,
    "错因本": mistakes.render,
}


def _install_copy_shortcut_guard() -> None:
    components.html(
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
          if (rootWindow.__intpCopyShortcutGuardInstalled) return;
          rootWindow.__intpCopyShortcutGuardInstalled = true;

          const isCopyShortcut = (event) =>
            (event.ctrlKey || event.metaKey) &&
            !event.altKey &&
            String(event.key || '').toLowerCase() === 'c';

          const stopStreamlitCacheShortcut = (event) => {
            if (!isCopyShortcut(event)) return;
            // Keep browser copy behavior, but stop Streamlit's global shortcut handler.
            event.stopPropagation();
            if (typeof event.stopImmediatePropagation === 'function') {
              event.stopImmediatePropagation();
            }
          };

          rootWindow.addEventListener('keydown', stopStreamlitCacheShortcut, true);
          rootWindow.document.addEventListener('keydown', stopStreamlitCacheShortcut, true);
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def main() -> None:
    st.set_page_config(
        page_title="INTP Study Manager",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _install_copy_shortcut_guard()
    init_db()
    ensure_default_api_providers()

    st.sidebar.title("INTP Study Manager")
    st.sidebar.caption("问题驱动 · 闭卷回忆 · 错因分析 · 间隔复习")
    page_name = st.sidebar.radio("页面", list(PAGES.keys()))
    st.sidebar.divider()
    st.sidebar.markdown("**70% 原则**")
    st.sidebar.caption("掌握度达到 70% 可前进，低于 70% 自动进入重点关注。")

    PAGES[page_name]()


if __name__ == "__main__":
    main()
