from __future__ import annotations

from pathlib import Path

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

PAGES = {
    "首页 Dashboard": dashboard.render,
    "PPT 逐页讲解": ppt_tutor.render,
    "PPT 与插问管理": ppt_management.render,
    "每日复盘提醒": reminders.render,
    "API 接入设置": api_settings.render,
    "学习登记": study_sessions.render,
    "知识点卡片": knowledge_cards.render,
    "闭卷测试 Prompt": quiz_prompts.render,
    "复习计划": reviews.render,
    "探索停车场": parking_lot.render,
    "主线与插问": mainline_branches.render,
    "错因本": mistakes.render,
}


def _install_browser_dom_guard() -> None:
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

    st.sidebar.title("INTP Study Manager")
    st.sidebar.caption("问题驱动 · 闭卷回忆 · 错因分析 · 间隔复习")
    page_name = st.sidebar.radio("页面", list(PAGES.keys()))
    st.sidebar.divider()
    st.sidebar.markdown("**70% 原则**")
    st.sidebar.caption("掌握度达到 70% 可前进，低于 70% 自动进入重点关注。")

    PAGES[page_name]()


if __name__ == "__main__":
    main()
