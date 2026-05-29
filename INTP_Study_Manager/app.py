from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from db import init_db
from pages import (
    admin_panel,
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
    AUTH_SESSION_COOKIE_NAME,
    AUTH_SESSION_EXPIRES_AT_KEY,
    AUTH_SESSION_IDLE_SECONDS,
    AUTH_SESSION_TOKEN_KEY,
    bootstrap_admin,
    format_bytes,
    get_current_user,
    get_user_upload_usage,
    has_initialized_admin,
    initialize_first_admin,
    login,
    logout,
    record_browser_activity_ping,
    register_by_invite,
    require_login,
    restore_current_user_from_device_session,
    refresh_device_session_activity,
    ensure_auth_tables,
)

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

ADMIN_PAGES = {
    "管理员后台": admin_panel.render,
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


def _install_auth_session_browser_guard() -> None:
    token = str(st.session_state.get(AUTH_SESSION_TOKEN_KEY) or "").strip()
    expires_at = int(st.session_state.get(AUTH_SESSION_EXPIRES_AT_KEY) or 0)
    components.html(
        f"""
        <script>
        (() => {{
          const cookieName = {AUTH_SESSION_COOKIE_NAME!r};
          const token = {token!r};
          const expiresAt = {expires_at};
          const idleMs = {AUTH_SESSION_IDLE_SECONDS * 1000};
          let rootWindow;
          try {{
            rootWindow = window.parent || window;
            void rootWindow.document;
          }} catch {{
            rootWindow = window;
          }}
          const doc = rootWindow.document;
          const sameSite = rootWindow.location.protocol === 'https:' ? '; SameSite=Lax; Secure' : '; SameSite=Lax';
          const cookieValue = (sessionToken, activityAt) => `${{sessionToken}}:${{Math.floor(Number(activityAt || Date.now()))}}`;
          const setCookie = (sessionToken, maxAge, activityAt) => {{
            doc.cookie = `${{cookieName}}=${{encodeURIComponent(cookieValue(sessionToken, activityAt))}}; Path=/; Max-Age=${{maxAge}}${{sameSite}}`;
          }};
          const clearCookie = () => {{
            doc.cookie = `${{cookieName}}=; Path=/; Max-Age=0${{sameSite}}`;
          }};
          if (token && expiresAt > 0) {{
            const activityAt = rootWindow.__intpAuthSessionLastActivity || Date.now();
            setCookie(token, {AUTH_SESSION_IDLE_SECONDS}, activityAt);
          }} else if (expiresAt === 0) {{
            clearCookie();
            delete rootWindow.__intpAuthSessionLastActivity;
          }}
          if (rootWindow.__intpAuthSessionGuardInstalled) {{
            if (token) {{
              rootWindow.__intpAuthSessionToken = token;
            }}
            return;
          }}
          rootWindow.__intpAuthSessionGuardInstalled = true;
          rootWindow.__intpAuthSessionToken = token || rootWindow.__intpAuthSessionToken || '';
          rootWindow.__intpAuthSessionLastActivity = Date.now();
          let lastPingAt = 0;
          let expiring = false;
          const activityEvents = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'input', 'change'];
          const pingActivity = () => {{
            const currentToken = rootWindow.__intpAuthSessionToken;
            if (!currentToken || expiring) return;
            rootWindow.__intpAuthSessionLastActivity = Date.now();
            setCookie(currentToken, {AUTH_SESSION_IDLE_SECONDS}, rootWindow.__intpAuthSessionLastActivity);
            const now = Date.now();
            if (now - lastPingAt < 15000) return;
            lastPingAt = now;
            try {{
              const url = new URL(rootWindow.location.href);
              url.searchParams.set('intp_auth_ping', String(now));
              rootWindow.history.replaceState(null, '', url.toString());
            }} catch {{}}
          }};
          const expireIfIdle = () => {{
            const currentToken = rootWindow.__intpAuthSessionToken;
            if (!currentToken || expiring) return;
            const lastActivity = Number(rootWindow.__intpAuthSessionLastActivity || 0);
            if (Date.now() - lastActivity < idleMs) return;
            expiring = true;
            clearCookie();
            rootWindow.__intpAuthSessionToken = '';
            try {{
              const url = new URL(rootWindow.location.href);
              url.searchParams.set('intp_auth_expired', String(Date.now()));
              rootWindow.location.replace(url.toString());
            }} catch {{
              rootWindow.location.reload();
            }}
          }};
          activityEvents.forEach((eventName) => rootWindow.addEventListener(eventName, pingActivity, true));
          rootWindow.setInterval(expireIfIdle, 5000);
        }})();
        </script>
        """,
        height=1,
        width=1,
    )


def _consume_auth_activity_query_params() -> None:
    if "intp_auth_ping" in st.query_params:
        token = str(st.session_state.get(AUTH_SESSION_TOKEN_KEY) or "").strip()
        try:
            activity_at = int(str(st.query_params.get("intp_auth_ping") or "0"))
        except ValueError:
            activity_at = None
        if token:
            record_browser_activity_ping(token, activity_at=activity_at)
        del st.query_params["intp_auth_ping"]
    if "intp_auth_expired" in st.query_params:
        logout()
        del st.query_params["intp_auth_expired"]


def _config_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    secrets_paths = (
        Path.home() / ".streamlit" / "secrets.toml",
        Path(__file__).resolve().parent / ".streamlit" / "secrets.toml",
    )
    if not any(path.exists() for path in secrets_paths):
        return default
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


def _render_first_admin_setup() -> None:
    st.title("INTP Study Manager")
    st.caption("首次使用，请先创建管理员账户。")

    with st.form("first_admin_setup"):
        username = st.text_input("管理员用户名", value="admin")
        display_name = st.text_input("显示名称", value="管理员")
        password = st.text_input("管理员密码", type="password")
        confirm_password = st.text_input("确认密码", type="password")
        submitted = st.form_submit_button("创建管理员", type="primary")
    if not submitted:
        return
    if not username.strip():
        st.error("管理员用户名不能为空。")
        return
    if not password:
        st.error("管理员密码不能为空。")
        return
    if password != confirm_password:
        st.error("两次输入的密码不一致。")
        return
    try:
        initialize_first_admin(username.strip(), password, display_name=display_name.strip() or username.strip())
        st.success("管理员创建成功，请直接登录。")
        st.rerun()
    except Exception as exc:
        st.error(str(exc))


def _render_auth_gate() -> None:
    if not has_initialized_admin():
        _render_first_admin_setup()
        return

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
    usage = get_user_upload_usage(user.id)
    st.sidebar.markdown(
        f"""**当前用户**
{user.display_name}
`{user.username}`
角色：{user.role}"""
    )
    st.sidebar.caption(f"上传容量：{format_bytes(usage['used_bytes'])} / {format_bytes(usage['quota_bytes'])}")
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
    _consume_auth_activity_query_params()

    user = restore_current_user_from_device_session()
    user = refresh_device_session_activity()
    if not user:
        _install_auth_session_browser_guard()
        _render_auth_gate()
        return
    _install_auth_session_browser_guard()
    ensure_default_api_providers()

    st.sidebar.title("INTP Study Manager")
    st.sidebar.caption("问题驱动 · 闭卷回忆 · 错因分析 · 间隔复习")
    _render_user_bar()
    available_pages = dict(PAGES)
    if user.role == "admin":
        available_pages.update(ADMIN_PAGES)
    page_name = st.sidebar.radio("页面", list(available_pages.keys()))
    st.sidebar.divider()
    st.sidebar.markdown("**70% 原则**")
    st.sidebar.caption("掌握度达到 70% 可前进，低于 70% 自动进入重点关注。")

    available_pages[page_name]()


if __name__ == "__main__":
    main()
