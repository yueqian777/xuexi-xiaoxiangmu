from __future__ import annotations

import pandas as pd
import streamlit as st

from services.auth_service import (
    create_invite,
    list_invites,
    list_users,
    require_admin,
    set_invite_active,
    set_user_active,
)


def render() -> None:
    admin = require_admin()
    st.title("管理员后台")
    st.caption("管理普通用户和邀请码。")

    tab_invite_create, tab_invites, tab_users = st.tabs(["创建邀请码", "邀请码管理", "用户管理"])

    with tab_invite_create:
        _render_create_invite(admin.id)
    with tab_invites:
        _render_invites()
    with tab_users:
        _render_users(admin.id)


def _render_create_invite(admin_user_id: int) -> None:
    st.subheader("创建邀请码")
    with st.form("create_invite_form"):
        cols = st.columns(3)
        role = cols[0].selectbox("角色", ["user"], format_func=lambda value: "普通用户")
        max_uses = int(cols[1].number_input("可使用次数", min_value=1, max_value=1000, value=1, step=1))
        expires_in_days = int(cols[2].number_input("有效天数", min_value=0, max_value=3650, value=7, step=1, help="填 0 表示不过期。"))
        submitted = st.form_submit_button("生成邀请码", type="primary")
    if submitted:
        code = create_invite(role=role, created_by=admin_user_id, max_uses=max_uses, expires_in_days=expires_in_days)
        st.success("邀请码已创建。")
        st.code(code, language="text")


def _render_invites() -> None:
    st.subheader("邀请码管理")
    invites = list_invites()
    if not invites:
        st.info("暂无邀请码。")
        return

    frame = pd.DataFrame(invites)[["code", "role", "max_uses", "used_count", "expires_at", "is_active", "created_by_name", "created_at"]]
    st.dataframe(frame, use_container_width=True, hide_index=True)

    invite_by_code = {str(item["code"]): item for item in invites}
    code = st.selectbox("选择邀请码", list(invite_by_code), format_func=lambda item: _invite_label(invite_by_code[item]))
    invite = invite_by_code[code]
    cols = st.columns(2)
    if cols[0].button("停用邀请码", disabled=not bool(invite["is_active"])):
        set_invite_active(code, False)
        st.success("邀请码已停用。")
        st.rerun()
    if cols[1].button("启用邀请码", disabled=bool(invite["is_active"])):
        set_invite_active(code, True)
        st.success("邀请码已启用。")
        st.rerun()


def _render_users(current_admin_id: int) -> None:
    st.subheader("用户管理")
    users = list_users()
    if not users:
        st.info("暂无用户。")
        return

    frame = pd.DataFrame(users)[["id", "username", "display_name", "role", "is_active", "created_at", "updated_at"]]
    st.dataframe(frame, use_container_width=True, hide_index=True)

    user_by_id = {int(item["id"]): item for item in users}
    user_id = st.selectbox("选择用户", list(user_by_id), format_func=lambda item: _user_label(user_by_id[item]))
    user = user_by_id[user_id]
    is_self = int(user_id) == int(current_admin_id)
    cols = st.columns(2)
    if cols[0].button("禁用用户", disabled=(not bool(user["is_active"])) or is_self):
        set_user_active(int(user_id), False)
        st.success("用户已禁用。")
        st.rerun()
    if cols[1].button("启用用户", disabled=bool(user["is_active"])):
        set_user_active(int(user_id), True)
        st.success("用户已启用。")
        st.rerun()
    if is_self:
        st.caption("当前登录管理员不能在这里禁用自己。")


def _invite_label(invite: dict) -> str:
    return f"{invite['code']} · {'启用' if invite['is_active'] else '停用'} · 已用 {invite['used_count']}/{invite['max_uses']}"


def _user_label(user: dict) -> str:
    role = '管理员' if user['role'] == 'admin' else '普通用户'
    state = '启用' if user['is_active'] else '禁用'
    return f"#{user['id']} · {user['username']} · {role} · {state}"
