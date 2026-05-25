from __future__ import annotations

import os

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
from services.auth_service import (
    bootstrap_admin,
    get_current_user,
    login,
    logout,
    register_by_invite,
    require_login,
    ensure_auth_tables,
)

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
        """,
        height=1,
        width=1,
    )


def _config_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def _seed_admin_from_env() -> None:
    username = _config_value("INTP_ADMIN_USERNAME")
    password = _config_value("INTP_ADMIN_PASSWORD")
    display_name = _config_value("INTP_ADMIN_DISPLAY_NAME", "管理员")
    if username and password:
        bootstrap_admin(username=username, password=password, display_name=display_name)


def _render_auth_gate() -> None:
    st.title("INTP Study Manager")
    st.caption("请先登录或使用邀请码加入。")

    tab_login, tab_join = st.tabs(["登录", "邀请码加入"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录")
        if submitted:
            try:
                login(username, password)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with tab_join:
        with st.form("invite_join_form"):
            username = st.text_input("用户名", key="invite_username")
            display_name = st.text_input("显示名称", key="invite_display_name")
            password = st.text_input("密码", type="password", key="invite_password")
            invite_code = st.text_input("邀请码", key="invite_code")
            submitted = st.form_submit_button("注册并登录")
        if submitted:
            try:
                register_by_invite(username, password, invite_code, display_name=display_name or username)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_user_bar() -> None:
    user = get_current_user()
    if not user:
        return
    st.sidebar.markdown(
        f"""**当前用户**
{user.display_name}
`{user.username}`
角色：{user.role}"""
    )
    if st.sidebar.button("退出登录", key="logout_button"):
        logout()
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="INTP Study Manager",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _install_browser_dom_guard()
    init_db()
    ensure_auth_tables()
    _seed_admin_from_env()

    user = get_current_user()
    if not user:
        _render_auth_gate()
        return
    ensure_default_api_providers()

    st.sidebar.title("INTP Study Manager")
    st.sidebar.caption("问题驱动 · 闭卷回忆 · 错因分析 · 间隔复习")
    _render_user_bar()
    page_name = st.sidebar.radio("页面", list(PAGES.keys()))
    st.sidebar.divider()
    st.sidebar.markdown("**70% 原则**")
    st.sidebar.caption("掌握度达到 70% 可前进，低于 70% 自动进入重点关注。")

    PAGES[page_name]()


if __name__ == "__main__":
    main()
