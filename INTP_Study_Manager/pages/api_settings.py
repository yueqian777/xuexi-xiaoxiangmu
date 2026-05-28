from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from services.ai_service import (
    AIServiceError,
    DEFAULT_MODEL,
    PROVIDER_TYPES,
    delete_api_provider,
    delete_api_providers,
    generate_text,
    list_api_providers,
    move_api_provider,
    provider_label,
    save_api_provider,
    save_api_provider_order,
)
from services import api_parallel_benchmark_service as parallel_benchmark
from services.api_key_ui import render_local_secret_unlock
from services.api_runtime import ensure_provider_model, provider_model_state_key
from services.auth_service import require_login
from services.balance_service import (
    BALANCE_QUERY_TYPES,
    BalanceQueryError,
    balance_query_label,
    load_balance_query_config,
    query_provider_balance,
    save_balance_query_config,
    WALLET_PROVIDER_HINTS,
)
from services.secret_store import (
    CRYPTOGRAPHY_AVAILABLE,
    SECRET_STORE_PATH,
    SecretStoreError,
    delete_provider_secret,
    get_provider_secret,
    load_secret_store,
    masked_secret,
    save_secret_store,
    secret_store_exists,
    upsert_provider_secret,
)

AUTH_TYPES = {
    "bearer": "Authorization: Bearer <key>",
    "x-api-key": "x-api-key: <key>",
    "api-key": "api-key: <key>",
    "x-goog-api-key": "x-goog-api-key: <key>",
    "query_key": "URL 查询参数 ?key=<key>",
    "none": "不使用 API Key",
}


def render() -> None:
    user = require_login()
    st.title("API 接入设置")
    st.caption("统一管理模型接口：OpenAI、OpenAI 兼容代理、Anthropic、Gemini，以及任意自定义 HTTP JSON API。")

    providers = list_api_providers()
    if providers:
        st.subheader("当前 Provider")
        overview = pd.DataFrame(providers)[
            [
                "sort_order",
                "name",
                "provider_type",
                "base_url",
                "model",
                "api_key_env",
                "auth_type",
                "enabled",
            ]
        ]
        st.dataframe(
            overview,
            column_config={
                "sort_order": st.column_config.NumberColumn("编号", disabled=True),
                "name": st.column_config.TextColumn("名称", disabled=True),
                "provider_type": st.column_config.TextColumn("类型", disabled=True),
                "base_url": st.column_config.TextColumn("Base URL / Endpoint", disabled=True),
                "model": st.column_config.TextColumn("模型", disabled=True),
                "api_key_env": st.column_config.TextColumn("环境变量", disabled=True),
                "auth_type": st.column_config.TextColumn("鉴权", disabled=True),
                "enabled": st.column_config.CheckboxColumn("启用", disabled=True),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("暂无 Provider。应用启动时会自动创建默认模板。")

    if user.role == "admin":
        tab_manage, tab_balance, tab_edit, tab_custom, tab_vault, tab_test, tab_help = st.tabs(
            ["编号 / 删除", "余额查询", "编辑 Provider", "新增自定义 API", "加密 API Key", "测试调用", "填写参考"]
        )

        with tab_manage:
            _render_provider_management(providers)

        with tab_balance:
            _render_balance_query(providers)

        with tab_edit:
            _render_edit_provider(providers)

        with tab_custom:
            _render_create_provider()
    else:
        tab_vault, tab_test, tab_help = st.tabs(["加密 API Key", "测试调用", "填写参考"])
        st.info("Provider 模板由管理员统一维护。普通用户可以在这里保存自己的加密 API Key 并测试调用。")

    with tab_vault:
        _render_secret_vault(providers)

    with tab_test:
        _render_test_provider(providers)

    with tab_help:
        _render_help()


def _render_provider_management(providers: list[dict]) -> None:
    st.subheader("编号 / 启用 / 删除")
    st.caption("“编号”就是 API 管理页面的连续编号。保存时会自动整理成 1、2、3...；常用 API 也可以用下方按钮快速置顶或上移。")
    if not providers:
        st.warning("没有可管理的 Provider。")
        return

    frame = _provider_management_frame(providers)
    frame["delete"] = False
    edited = st.data_editor(
        frame,
        use_container_width=True,
        hide_index=True,
        disabled=["provider_key", "name", "provider_type", "base_url", "model"],
        column_order=["sort_order", "name", "provider_type", "base_url", "model", "enabled", "delete"],
        column_config={
            "sort_order": st.column_config.NumberColumn("编号", min_value=1, step=1),
            "name": st.column_config.TextColumn("名称", disabled=True),
            "provider_type": st.column_config.TextColumn("类型", disabled=True),
            "base_url": st.column_config.TextColumn("Base URL / Endpoint", disabled=True),
            "model": st.column_config.TextColumn("模型", disabled=True),
            "enabled": st.column_config.CheckboxColumn("启用"),
            "delete": st.column_config.CheckboxColumn("删除"),
        },
        key="api_provider_management_editor",
    )
    selected_delete_keys = [
        str(row["provider_key"])
        for _, row in edited.iterrows()
        if bool(row.get("delete"))
    ]

    cols = st.columns([1.1, 1.1, 2])
    if cols[0].button("保存编号 / 启用状态", type="primary", key="save_api_provider_order"):
        save_api_provider_order(edited.to_dict("records"))
        st.success("Provider 编号和启用状态已保存，编号已自动连续。")
        st.rerun()

    provider_key = cols[1].selectbox(
        "常用 API 快速调整",
        [p["provider_key"] for p in providers],
        format_func=lambda item_key: provider_label(next(p for p in providers if p["provider_key"] == item_key)),
        key="api_provider_quick_order_key",
        label_visibility="collapsed",
    )
    move_cols = cols[2].columns(3)
    if move_cols[0].button("上移一位", key="quick_move_provider_up"):
        move_api_provider(provider_key, offset=-1)
        st.rerun()
    if move_cols[1].button("置顶常用 API", key="quick_move_provider_top"):
        move_api_provider(provider_key, to_top=True)
        st.rerun()
    if move_cols[2].button("下移一位", key="quick_move_provider_down"):
        move_api_provider(provider_key, offset=1)
        st.rerun()

    with st.expander("删除勾选的 Provider", expanded=bool(selected_delete_keys)):
        if selected_delete_keys:
            names = [
                provider_label(provider)
                for provider in providers
                if str(provider["provider_key"]) in selected_delete_keys
            ]
            st.warning("将删除：" + "；".join(names))
        else:
            st.caption("在上方表格勾选“删除”后，可以在这里确认删除。")
        confirm_delete = st.checkbox(
            "确认删除上表勾选的 Provider",
            value=False,
            key="confirm_delete_selected_api_providers",
            disabled=not selected_delete_keys,
        )
        if st.button(
            "删除勾选 Provider",
            type="primary",
            key="delete_selected_api_providers",
            disabled=not selected_delete_keys or not confirm_delete,
        ):
            _delete_providers_and_cleanup(selected_delete_keys)
            st.success("已删除勾选 Provider，并重新整理编号。")
            st.rerun()


def _provider_management_frame(providers: list[dict]) -> pd.DataFrame:
    columns = ["provider_key", "sort_order", "name", "provider_type", "base_url", "model", "enabled"]
    frame = pd.DataFrame(providers)
    for column in columns:
        if column not in frame.columns:
            frame[column] = "" if column != "enabled" else True
    frame = frame[columns].copy()
    frame["provider_key"] = frame["provider_key"].astype(str)
    frame["sort_order"] = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype(int)
    frame["enabled"] = frame["enabled"].astype(bool)
    return frame


def _render_balance_query(providers: list[dict]) -> None:
    require_login()
    st.subheader("远程余量 / Plan 查询")
    st.caption(
        "不再读取本地浏览器缓存或本地数据库；所有结果都来自你选择的 Provider 远程接口。"
        f"内置模板：{'、'.join(WALLET_PROVIDER_HINTS)}；未覆盖的厂商请用自定义 HTTP JSON。"
    )
    st.info(
        "先判断你要查的是哪种额度：普通 API 钱包余额用 API Key；订阅 / Plan 额度通常用账号或 Token Plan Key；"
        "New API / One API 网关额度通常用管理端 Access Token。不同 Key 不能混用。"
    )
    with st.expander("CC Switch 适配范围", expanded=False):
        st.markdown(
            """
- Token Plan：Kimi For Coding、智谱 GLM、MiniMax。
- 第三方钱包余额：DeepSeek、StepFun、SiliconFlow、OpenRouter、Novita AI。
- 网关模板：New API / One API 的 `/api/user/self`，以及通用 `/user/balance`。
- 兜底扩展：任何未覆盖服务商都可以用“自定义 HTTP JSON”配置 URL、请求头和字段路径。
- 官方登录订阅：Claude / Codex / Gemini / Copilot 这类依赖客户端 OAuth 或登录态的额度，不等同于普通模型 API Key 余额；本项目保留独立 Plan 查询，不自动读取本地登录态。
            """
        )

    if not providers:
        st.warning("没有可查询的 Provider。")
        return

    enabled = [provider for provider in providers if provider["enabled"]] or providers
    provider_key = st.selectbox(
        "选择要查询的 Provider",
        [provider["provider_key"] for provider in enabled],
        format_func=lambda item_key: provider_label(next(p for p in enabled if p["provider_key"] == item_key)),
        key="balance_provider_key",
    )
    provider = next(item for item in enabled if item["provider_key"] == provider_key)
    config = load_balance_query_config(provider)
    saved_type = str(provider.get("balance_query_type") or "auto_wallet")
    if saved_type not in BALANCE_QUERY_TYPES:
        saved_type = "auto_wallet"

    left, right = st.columns([1.05, 1])
    with left:
        st.markdown("**查询配置**")
        enabled_query = st.checkbox(
            "启用这个 Provider 的远程余量查询",
            value=bool(provider.get("balance_query_enabled")),
            key=f"balance_enabled_{provider_key}",
        )
        query_type = st.selectbox(
            "查询方式",
            list(BALANCE_QUERY_TYPES.keys()),
            index=list(BALANCE_QUERY_TYPES.keys()).index(saved_type),
            format_func=balance_query_label,
            key=f"balance_query_type_{provider_key}",
            help="不确定时先选自动识别；Kimi / 智谱 / MiniMax 的套餐额度请选对应 Token Plan。",
        )
        _render_balance_query_explainer(query_type)

        current_config = _render_balance_config_form(provider, query_type, config)
        cols = st.columns(2)
        if cols[0].button("保存查询配置", key=f"save_balance_query_config_{provider_key}"):
            save_balance_query_config(
                provider_key,
                enabled=enabled_query,
                query_type=query_type,
                config=current_config,
            )
            st.success("远程余量查询配置已保存。敏感凭据没有写入 SQLite。")
            st.rerun()
        if cols[1].button("清空上次结果", key=f"clear_balance_result_{provider_key}"):
            st.session_state.pop("last_provider_balance_result", None)
            st.rerun()

    with right:
        st.markdown("**查询凭据**")
        key_name = f"api_key_provider_{provider_key}"
        active_model = provider.get("model") or DEFAULT_MODEL
        render_local_secret_unlock(
            provider,
            model=active_model,
            target_session_key=key_name,
            key_prefix=f"balance_provider_{provider_key}",
            widget_session_key=f"balance_credential_{provider_key}",
        )
        credential_label = _balance_credential_label(query_type)
        placeholder_env = (
            current_config.get("access_token_env")
            if query_type in {"newapi_user", "openai_plan"}
            else current_config.get("credential_env")
        ) or provider.get("api_key_env") or "未设置"
        credential = st.text_input(
            credential_label,
            value=st.session_state.get(key_name, ""),
            type="password",
            placeholder=f"可留空改用环境变量 {placeholder_env}",
            key=f"balance_credential_{provider_key}",
        )
        st.session_state[key_name] = credential
        st.caption("这里的凭据只保存在当前会话；如需长期保存，请用“加密 API Key”页签。")

        if st.button("查询当前 Provider 余量", type="primary", key=f"query_provider_balance_{provider_key}"):
            try:
                result = query_provider_balance(
                    provider,
                    credential=credential,
                    query_type=query_type,
                    config=current_config,
                )
                st.session_state["last_provider_balance_result"] = result
            except BalanceQueryError as exc:
                st.error(str(exc))
        _render_balance_result(st.session_state.get("last_provider_balance_result"))


def _render_balance_config_form(provider: dict, query_type: str, config: dict) -> dict:
    updated = dict(config)
    base_url_default = str(config.get("base_url") or "")
    with st.expander("通用参数", expanded=True):
        cols = st.columns(2)
        updated["base_url"] = cols[0].text_input(
            "余额查询 Base URL 覆盖（可选）",
            value=base_url_default,
            placeholder=provider.get("base_url") or "留空使用 Provider Base URL",
            key=f"balance_base_url_{provider['provider_key']}",
        )
        updated["timeout"] = cols[1].number_input(
            "请求超时（秒）",
            min_value=2,
            max_value=30,
            value=int(config.get("timeout") or 10),
            step=1,
            key=f"balance_timeout_{provider['provider_key']}",
        )
        updated["credential_env"] = st.text_input(
            "凭据环境变量名（可选）",
            value=str(config.get("credential_env") or provider.get("api_key_env") or ""),
            key=f"balance_credential_env_{provider['provider_key']}",
            help="手动输入和加密密钥库优先；这里仅作为兜底。",
        )

    if query_type == "kimi_token_plan":
        with st.expander("Kimi For Coding Token Plan 参数", expanded=True):
            st.caption(
                "按 CC Switch 的 Token Plan 模板查询：GET `https://api.kimi.com/coding/v1/usages`。"
                "请使用 Kimi For Coding 对应的 API Key；普通 Moonshot/Kimi Chat API Key 不一定有这个额度接口权限。"
            )

    if query_type == "zhipu_token_plan":
        with st.expander("智谱 GLM Token Plan 参数", expanded=True):
            st.caption(
                "按 CC Switch 的 Token Plan 模板查询：GET `https://api.z.ai/api/monitor/usage/quota/limit`。"
                "鉴权头是 `Authorization: <api_key>`，不是 Bearer。返回值通常是 5 小时窗口和周窗口的已用百分比。"
            )

    if query_type == "minimax_token_plan":
        with st.expander("MiniMax Token Plan / Credits 参数", expanded=True):
            updated["group_id"] = st.text_input(
                "Team / Group ID（可选）",
                value=str(config.get("group_id") or ""),
                key=f"balance_minimax_group_id_{provider['provider_key']}",
                help="官方 Token Plan 查询通常不需要填；旧版兼容端点或团队账号可能需要。可在 MiniMax 控制台基础信息里查看。",
            )
            st.caption(
                "按 CC Switch 的 Token Plan 模板查询：优先请求 api.minimaxi.com / api.minimax.io 的 "
                "`/v1/api/openplatform/coding_plan/remains`。这里查的是 Token Plan / Credits 请求额度，不是普通按量付费钱包余额。"
                "MiniMax 普通 Open Platform API Key 的余额请到官网 Account > Billing > Balance 查看。"
            )

    if query_type == "newapi_user":
        with st.expander("New API / One API 参数", expanded=True):
            cols = st.columns(2)
            updated["user_id"] = cols[0].text_input(
                "User ID（可选）",
                value=str(config.get("user_id") or ""),
                key=f"balance_user_id_{provider['provider_key']}",
            )
            updated["quota_unit"] = cols[1].number_input(
                "额度换算系数",
                min_value=1,
                value=int(config.get("quota_unit") or 500000),
                step=1000,
                key=f"balance_quota_unit_{provider['provider_key']}",
                help="New API 常见换算是 quota / 500000。",
            )
            updated["access_token_env"] = st.text_input(
                "Access Token 环境变量名（可选）",
                value=str(config.get("access_token_env") or ""),
                key=f"balance_access_token_env_{provider['provider_key']}",
                help="如果模型 API Key 和管理端 Access Token 不是同一个，请在这里指定管理端 Token 的环境变量名。",
            )
            st.caption(
                "按 CC Switch 的 New API 模板查询：GET `{baseUrl}/api/user/self`，"
                "Authorization 使用管理端 Access Token。Sub2API / 环城网安这类网关如果只给模型调用 Key，通常查不了用户额度。"
            )

    if query_type == "openai_plan":
        with st.expander("官方 Plan 参数", expanded=True):
            updated["account_id"] = st.text_input(
                "ChatGPT Account ID（可选）",
                value=str(config.get("account_id") or ""),
                key=f"balance_account_id_{provider['provider_key']}",
            )
            st.caption("官方 Plan 查询需要你手动提供账号 Access Token；本项目不会从本地软件或浏览器读取登录态。")

    if query_type == "generic_wallet":
        with st.expander("通用钱包接口参数", expanded=False):
            updated["generic_path"] = st.text_input(
                "接口路径",
                value=str(config.get("generic_path") or "/user/balance"),
                key=f"balance_generic_path_{provider['provider_key']}",
            )
            updated["unit_value"] = st.text_input(
                "默认单位",
                value=str(config.get("unit_value") or "USD"),
                key=f"balance_generic_unit_{provider['provider_key']}",
            )
            st.caption(
                "按 CC Switch 的通用模板查询：GET `{baseUrl}/user/balance`，并期望远程返回 JSON。"
                "如果服务商返回的是网页 HTML 或必须登录管理后台，请改用 New API / One API 或自定义 HTTP JSON。"
            )

    if query_type == "custom_http_json":
        with st.expander("自定义 HTTP JSON", expanded=True):
            st.caption("支持占位符：`{{apiKey}}`、`{{accessToken}}`、`{{baseUrl}}`、`{{origin}}`、`{{model}}`、`{{accountId}}`、`{{userId}}`。")
            updated["custom_url"] = st.text_input(
                "完整查询 URL",
                value=str(config.get("custom_url") or ""),
                key=f"balance_custom_url_{provider['provider_key']}",
            )
            updated["custom_method"] = st.selectbox(
                "HTTP 方法",
                ["GET", "POST", "PUT"],
                index=["GET", "POST", "PUT"].index(str(config.get("custom_method") or "GET").upper())
                if str(config.get("custom_method") or "GET").upper() in {"GET", "POST", "PUT"}
                else 0,
                key=f"balance_custom_method_{provider['provider_key']}",
            )
            updated["custom_headers_json"] = st.text_area(
                "请求头 JSON",
                value=str(config.get("custom_headers_json") or '{"Accept":"application/json"}'),
                height=90,
                key=f"balance_custom_headers_{provider['provider_key']}",
            )
            updated["custom_body"] = st.text_area(
                "请求体模板（可选）",
                value=str(config.get("custom_body") or ""),
                height=90,
                key=f"balance_custom_body_{provider['provider_key']}",
            )
            path_cols = st.columns(3)
            updated["remaining_path"] = path_cols[0].text_input("剩余额度路径", value=str(config.get("remaining_path") or ""), key=f"balance_remaining_path_{provider['provider_key']}")
            updated["total_path"] = path_cols[1].text_input("总额度路径", value=str(config.get("total_path") or ""), key=f"balance_total_path_{provider['provider_key']}")
            updated["used_path"] = path_cols[2].text_input("已用额度路径", value=str(config.get("used_path") or ""), key=f"balance_used_path_{provider['provider_key']}")
            path_cols = st.columns(3)
            updated["unit_path"] = path_cols[0].text_input("单位路径", value=str(config.get("unit_path") or ""), key=f"balance_unit_path_{provider['provider_key']}")
            updated["unit_value"] = path_cols[1].text_input("固定单位", value=str(config.get("unit_value") or ""), key=f"balance_unit_value_{provider['provider_key']}")
            updated["plan_name_path"] = path_cols[2].text_input("套餐名路径", value=str(config.get("plan_name_path") or ""), key=f"balance_plan_path_{provider['provider_key']}")
            path_cols = st.columns(2)
            updated["status_path"] = path_cols[0].text_input("状态路径", value=str(config.get("status_path") or ""), key=f"balance_status_path_{provider['provider_key']}")
            updated["reset_path"] = path_cols[1].text_input("重置时间路径", value=str(config.get("reset_path") or ""), key=f"balance_reset_path_{provider['provider_key']}")

    return updated


def _render_balance_query_explainer(query_type: str) -> None:
    explanations = {
        "auto_wallet": "自动识别会先按 CC Switch 的域名规则匹配，再尝试常见远程端点。内置覆盖 Kimi、智谱、MiniMax、DeepSeek、OpenRouter、SiliconFlow、StepFun、Novita、NewAPI/OneAPI。",
        "kimi_token_plan": "CC Switch Token Plan 模板：Kimi For Coding 的套餐额度，查询 /coding/v1/usages。",
        "zhipu_token_plan": "CC Switch Token Plan 模板：智谱 GLM 的套餐额度，查询 api.z.ai 的 quota/limit 接口。",
        "minimax_token_plan": "MiniMax 专用。请填 Token Plan Key / Credits Key；它查的是 5 小时滚动请求额度和周额度，不是普通按量付费余额。",
        "deepseek_wallet": "DeepSeek 官方钱包余额，填 DeepSeek API Key。",
        "openrouter_wallet": "OpenRouter Credits，填 OpenRouter API Key。",
        "siliconflow_wallet": "SiliconFlow 账户余额，填 SiliconFlow API Key。",
        "newapi_user": "CC Switch New API 模板：请求 /api/user/self。通常要填管理端 Access Token，不是用于模型调用的普通 API Key。",
        "openai_plan": "ChatGPT / Codex Plus、Pro、Team 等订阅额度查询，通常需要账号 Access Token；它不是 OpenAI API 钱包余额。",
        "generic_wallet": "CC Switch 通用模板：请求 /user/balance。只适合直接返回 JSON 余额的代理站。",
        "custom_http_json": "当服务商有自己的余额接口时使用。需要手动填 URL、请求头和返回字段路径。",
    }
    st.caption(explanations.get(query_type, "请选择与当前 Provider 匹配的远程查询方式。"))


def _balance_credential_label(query_type: str) -> str:
    if query_type in {"openai_plan", "newapi_user"}:
        return "Access Token"
    if query_type == "kimi_token_plan":
        return "Kimi For Coding API Key"
    if query_type == "zhipu_token_plan":
        return "智谱 GLM API Key"
    if query_type == "minimax_token_plan":
        return "MiniMax Token Plan Key / Credits Key"
    return "API Key / Access Token"


def _render_balance_result(result: dict | None) -> None:
    if not result:
        return
    with st.container(border=True):
        st.markdown(f"**{result.get('title') or '查询结果'}**")
        cols = st.columns(4)
        cols[0].metric("余量", result.get("amount_text") or "未知")
        cols[1].metric("状态", result.get("status") or "未知")
        cols[2].metric("来源", result.get("source") or "未知")
        cols[3].metric("更新时间", result.get("updated_at") or "未知")
        total = result.get("total")
        used = result.get("used")
        if isinstance(total, (int, float)) and total > 0 and isinstance(used, (int, float)):
            st.progress(min(1.0, max(0.0, float(used) / float(total))), text=f"已用 {used:.2f} / 总计 {total:.2f}")
        rows = result.get("rows") or []
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        details = result.get("details") or {}
        if details:
            with st.expander("明细"):
                st.json(details)


def _render_edit_provider(providers: list[dict]) -> None:
    if not providers:
        st.warning("没有可编辑的 Provider。")
        return
    provider_key = st.selectbox(
        "选择要编辑的 Provider",
        [p["provider_key"] for p in providers],
        format_func=lambda item_key: provider_label(next(p for p in providers if p["provider_key"] == item_key)),
    )
    provider = next(p for p in providers if p["provider_key"] == provider_key)
    _provider_form("更新 Provider", provider, provider_key)
    _render_provider_edit_actions(provider, providers)


def _render_create_provider() -> None:
    user = require_login()
    provider = {
        "name": "新的自定义 API",
        "provider_type": "custom_http_json",
        "base_url": "",
        "model": "",
        "api_key_env": "",
        "auth_type": "bearer",
        "extra_headers_json": "{}",
        "request_template_json": _default_custom_template(),
        "response_path": "choices.0.message.content",
        "enabled": 1,
        "sort_order": len(list_api_providers()) + 1,
    }
    _provider_form("创建 Provider", provider, None)


def _provider_form(title: str, provider: dict, provider_key: str | None) -> None:
    user = require_login()
    with st.form(f"provider_form_{provider_key or 'new'}"):
        st.subheader(title)
        cols = st.columns([1.2, 1.2, 0.6])
        name = cols[0].text_input("名称", value=provider.get("name", ""))
        provider_type = cols[1].selectbox(
            "Provider 类型",
            list(PROVIDER_TYPES.keys()),
            index=_index_or_zero(list(PROVIDER_TYPES.keys()), provider.get("provider_type")),
            format_func=lambda value: PROVIDER_TYPES[value],
        )
        sort_order = int(
            cols[2].number_input(
                "编号",
                min_value=1,
                value=_positive_int(provider.get("sort_order"), 1),
                step=1,
                help="这是 API 管理页面编号；保存后会自动重排为连续序号。",
            )
        )
        base_url = st.text_input(
            "Base URL / Endpoint",
            value=provider.get("base_url", ""),
            help="内置类型填 Base URL；自定义 HTTP JSON 填完整 POST endpoint。",
        )
        cols = st.columns(3)
        model = cols[0].text_input("模型", value=provider.get("model", "") or DEFAULT_MODEL)
        api_key_env = cols[1].text_input("API Key 环境变量名", value=provider.get("api_key_env", ""))
        auth_type = cols[2].selectbox(
            "鉴权方式",
            list(AUTH_TYPES.keys()),
            index=_index_or_zero(list(AUTH_TYPES.keys()), provider.get("auth_type")),
            format_func=lambda value: AUTH_TYPES[value],
        )
        extra_headers_json = st.text_area(
            "额外请求头 JSON",
            value=_pretty_json(provider.get("extra_headers_json") or "{}"),
            height=110,
            help='例如 {"anthropic-version":"2023-06-01"}',
        )
        request_template_json = st.text_area(
            "自定义请求体 JSON 模板",
            value=provider.get("request_template_json") or "",
            height=190,
            help="仅自定义 HTTP JSON 必填。可使用 {prompt}、{model}、{max_output_tokens}。",
        )
        response_path = st.text_input(
            "响应文本路径",
            value=provider.get("response_path", ""),
            help="例如 choices.0.message.content 或 candidates.0.content.parts.0.text",
        )
        enabled = st.checkbox("启用", value=bool(provider.get("enabled", 1)))
        submitted = st.form_submit_button(title)

    if not submitted:
        return
    if not name.strip():
        st.error("名称不能为空。")
        return
    try:
        save_api_provider(
            {
                "name": name,
                "provider_type": provider_type,
                "base_url": base_url,
                "model": model,
                "api_key_env": api_key_env,
                "auth_type": auth_type,
                "extra_headers_json": extra_headers_json,
                "request_template_json": request_template_json,
                "response_path": response_path,
                "enabled": enabled,
                "sort_order": sort_order,
            },
            provider_key,
        )
    except Exception as exc:
        st.error(f"保存失败：{exc}")
        return
    st.success("Provider 已保存，编号会在列表中自动连续。")
    st.rerun()


def _render_provider_edit_actions(provider: dict, providers: list[dict]) -> None:
    provider_key = str(provider["provider_key"])
    st.divider()
    st.subheader("快捷编号与删除")
    cols = st.columns(4)
    if cols[0].button("上移一位", key=f"edit_move_provider_up_{provider_key}"):
        move_api_provider(provider_key, offset=-1)
        st.rerun()
    if cols[1].button("置顶常用 API", key=f"edit_move_provider_top_{provider_key}"):
        move_api_provider(provider_key, to_top=True)
        st.rerun()
    if cols[2].button("下移一位", key=f"edit_move_provider_down_{provider_key}"):
        move_api_provider(provider_key, offset=1)
        st.rerun()
    cols[3].caption(f"当前编号：{_positive_int(provider.get('sort_order'), 1)} / {len(providers)}")

    with st.expander("删除这个 Provider", expanded=False):
        st.warning(f"删除后会从 API 列表移除：编号 {_positive_int(provider.get('sort_order'), 1)} · {provider.get('name')}")
        confirm = st.checkbox(
            "确认删除这个 Provider",
            key=f"confirm_delete_provider_{provider_key}",
        )
        if st.button(
            "删除当前 Provider",
            type="primary",
            key=f"delete_provider_{provider_key}",
            disabled=not confirm,
        ):
            if delete_api_provider(provider_key):
                _cleanup_deleted_provider_state([provider_key])
                st.success("Provider 已删除，编号已自动连续。")
                st.rerun()


def _delete_providers_and_cleanup(provider_keys: list[str]) -> None:
    delete_api_providers(provider_keys)
    _cleanup_deleted_provider_state(provider_keys)


def _cleanup_deleted_provider_state(provider_keys: list[str]) -> None:
    deleted = {str(provider_key) for provider_key in provider_keys}
    for provider_key in deleted:
        st.session_state.pop(f"api_key_provider_{provider_key}", None)
        st.session_state.pop(provider_model_state_key(provider_key), None)

    active_key = str(st.session_state.get("active_api_provider_key") or "")
    if active_key in deleted:
        st.session_state.pop("active_api_provider_key", None)
        st.session_state.pop("active_api_model", None)

    if not st.session_state.get("secret_vault_unlocked"):
        return
    data = st.session_state.get("secret_vault_data") or {"providers": {}}
    password = st.session_state.get("secret_vault_master_password", "")
    if not password:
        return
    updated = data
    for provider_key in deleted:
        updated = delete_provider_secret(updated, provider_key)
    try:
        save_secret_store(password, updated)
    except SecretStoreError as exc:
        st.warning(f"Provider 已删除，但加密 Key 清理失败：{exc}")
        return
    st.session_state["secret_vault_data"] = updated


def _render_test_provider(providers: list[dict]) -> None:
    enabled = [p for p in providers if p["enabled"]]
    if not enabled:
        st.warning("没有启用的 Provider。")
        return

    provider_key = st.selectbox(
        "选择测试 Provider",
        [p["provider_key"] for p in enabled],
        format_func=lambda item_key: provider_label(next(p for p in enabled if p["provider_key"] == item_key)),
        key="test_provider_key",
    )
    provider = next(p for p in enabled if p["provider_key"] == provider_key)
    key_name = f"api_key_provider_{provider_key}"
    ensure_provider_model(provider)
    model = st.text_input(
        "当前 API 临时模型",
        key=provider_model_state_key(provider_key),
        help="这个模型跟随当前 Provider 保存；切换测试 API 后会恢复该 API 自己的临时模型。",
    )
    active_model = model.strip() or provider.get("model") or DEFAULT_MODEL
    render_local_secret_unlock(
        provider,
        model=active_model,
        target_session_key=key_name,
        key_prefix=f"test_provider_{provider_key}",
        widget_session_key=f"api_key_provider_{provider_key}",
    )
    api_key = st.text_input(
        "临时 API Key",
        value=st.session_state.get(key_name, ""),
        type="password",
        placeholder=f"不填写则读取环境变量 {provider.get('api_key_env') or '未设置'}",
    )
    st.session_state[key_name] = api_key
    prompt = st.text_area(
        "测试 Prompt",
        value="请用一句中文回答：API Provider 调用成功。",
        height=120,
    )
    max_tokens = st.number_input("最大输出 token", min_value=128, max_value=8000, value=800, step=128)
    if st.button("发送测试请求", type="primary"):
        try:
            with st.spinner("正在请求 API..."):
                output = generate_text(
                    prompt,
                    provider_key=provider_key,
                    api_key=api_key,
                    model_override=active_model,
                    max_output_tokens=int(max_tokens),
                )
            st.success("调用成功。")
            st.markdown(output)
        except AIServiceError as exc:
            st.error(str(exc))


def _render_secret_vault(providers: list[dict]) -> None:
    require_login()
    st.subheader("本地加密 API Key 密钥库")
    st.caption(
        "API Key 会用你的主密码派生密钥后进行 AES-256-GCM 加密，只保存密文到本机。"
        "主密码不会写入数据库或文件；解锁后 Key 仅保存在当前 Streamlit 会话内存中。"
    )
    st.code(str(SECRET_STORE_PATH), language="text")
    if not CRYPTOGRAPHY_AVAILABLE:
        st.error("当前运行 Streamlit 的 Python 环境没有安装 cryptography，因此暂时不能使用加密 API Key 功能。")
        st.code("python -m pip install -r requirements.txt", language="powershell")
        st.caption("安装后重启 Streamlit。其他页面和普通 API 调用不受影响。")
        return

    if not providers:
        st.warning("请先创建或启用 Provider，再保存对应 API Key。")
        return

    if st.session_state.get("secret_vault_unlocked"):
        _render_unlocked_secret_vault(providers)
    else:
        _render_locked_secret_vault(providers)


def _render_locked_secret_vault(providers: list[dict]) -> None:
    exists = secret_store_exists()
    state_label = "已存在，输入主密码解锁" if exists else "尚未创建，设置主密码后创建"
    st.info(f"密钥库状态：{state_label}。")

    with st.form("unlock_secret_vault"):
        master_password = st.text_input("主密码", type="password")
        confirm_password = ""
        if not exists:
            confirm_password = st.text_input("再次输入主密码", type="password")
            st.caption("请记住这个主密码。忘记后无法恢复已加密的 API Key，只能重新录入。")
        submitted = st.form_submit_button("解锁 / 创建密钥库", type="primary")

    if not submitted:
        return
    if not master_password:
        st.error("主密码不能为空。")
        return
    if not exists and master_password != confirm_password:
        st.error("两次输入的主密码不一致。")
        return
    try:
        if exists:
            data = load_secret_store(master_password)
            save_secret_store(master_password, data)
        else:
            data = {"providers": {}}
            save_secret_store(master_password, data)
    except SecretStoreError as exc:
        st.error(str(exc))
        return

    st.session_state["secret_vault_unlocked"] = True
    st.session_state["secret_vault_data"] = data
    st.session_state["secret_vault_master_password"] = master_password
    _apply_vault_to_session(providers, data)
    st.success("密钥库已解锁，并已应用到当前会话。")
    st.rerun()


def _render_unlocked_secret_vault(providers: list[dict]) -> None:
    data = st.session_state.get("secret_vault_data") or {"providers": {}}
    saved = data.get("providers", {})
    st.success(f"密钥库已解锁。当前保存 {len(saved)} 个 Provider Key。")

    rows = _secret_vault_rows(providers, data)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    provider_key = st.selectbox(
        "选择要保存 / 更新 Key 的 Provider",
        [p["provider_key"] for p in providers],
        format_func=lambda item_key: provider_label(next(p for p in providers if p["provider_key"] == item_key)),
        key="secret_provider_key",
    )
    provider = next(p for p in providers if p["provider_key"] == provider_key)
    current_secret_key, current_secret_item = _saved_secret_for_provider(provider, data)
    current_secret = str((current_secret_item or {}).get("api_key") or "")
    with st.form("save_provider_secret"):
        api_key = st.text_input(
            "API Key",
            type="password",
            placeholder=f"当前：{masked_secret(current_secret)}；留空不会保存",
        )
        submitted = st.form_submit_button("加密保存这个 API Key", type="primary")
        measure_submitted = st.form_submit_button("保存并测速绑定")

    if submitted or measure_submitted:
        if submitted and not api_key.strip():
            st.error("API Key 不能为空。")
            return
        target_api_key = api_key.strip() or current_secret
        try:
            updated = data
            if api_key.strip():
                updated = upsert_provider_secret(
                    data,
                    provider_key=provider_key,
                    provider_name=provider["name"],
                    api_key=api_key,
                    model=provider.get("model") or "",
                    provider_type=provider.get("provider_type") or "",
                    base_url=provider.get("base_url") or "",
                )
                save_secret_store(st.session_state["secret_vault_master_password"], updated)
        except SecretStoreError as exc:
            st.error(str(exc))
            return
        st.session_state["secret_vault_data"] = updated
        st.session_state[f"api_key_provider_{provider_key}"] = target_api_key
        if measure_submitted:
            if not target_api_key:
                st.error("请先填写或保存当前 Provider 的 API Key 后再测速。")
                return
            _benchmark_and_bind_provider_key(provider, target_api_key)
        else:
            st.success("API Key 已加密保存，并已应用到当前会话。")
            st.rerun()

    cols = st.columns(3)
    if cols[0].button("应用全部已保存 Key 到当前会话"):
        _apply_vault_to_session(providers, data)
        st.success("已应用到当前会话。")
    if cols[1].button("删除当前 Provider 的已保存 Key", disabled=not bool(current_secret)):
        updated = delete_provider_secret(data, current_secret_key or provider_key)
        try:
            save_secret_store(st.session_state["secret_vault_master_password"], updated)
        except SecretStoreError as exc:
            st.error(str(exc))
            return
        st.session_state["secret_vault_data"] = updated
        st.session_state.pop(f"api_key_provider_{provider_key}", None)
        st.success("已删除当前 Provider 的加密 Key。")
        st.rerun()
    if cols[2].button("锁定并清除本次会话 Key"):
        _lock_secret_vault(providers)
        st.success("已锁定。")
        st.rerun()


def _benchmark_and_bind_provider_key(provider: dict, api_key: str) -> None:
    provider_key = str(provider.get("provider_key") or "")
    active_model = str(st.session_state.get(provider_model_state_key(provider_key)) or provider.get("model") or DEFAULT_MODEL)
    provider_config = {
        **provider,
        "provider_name": provider.get("name") or provider_key,
        "api_key": api_key,
        "active_model": active_model,
    }
    with st.spinner("正在按当前 API Key 测速并绑定最大并行路数..."):
        result = parallel_benchmark.probe_provider_parallel_limit(provider_config)
        parallel_benchmark.save_benchmark_result(result)
    limit = int(result.get("parallel_limit") or 0)
    success_rate = float(result.get("success_rate") or 0.0)
    samples = int(result.get("sample_count") or 0)
    if result.get("is_authoritative") and limit > 0:
        st.success(f"测速完成并已绑定到当前 API Key：{limit} 路，成功率 {success_rate:.0%}，样本 {samples} 次。")
    else:
        st.warning(f"测速完成但结论不可靠，已记录本地样本但未绑定：成功率 {success_rate:.0%}，样本 {samples} 次。")


def _apply_vault_to_session(providers: list[dict], data: dict) -> None:
    for provider in providers:
        provider_key = str(provider["provider_key"])
        _, item = _saved_secret_for_provider(provider, data)
        secret = str((item or {}).get("api_key") or "")
        if secret:
            st.session_state[f"api_key_provider_{provider_key}"] = secret


def _secret_vault_rows(providers: list[dict], data: dict) -> list[dict]:
    rows = []
    for raw_key, item in (data.get("providers", {}) or {}).items():
        if not isinstance(item, dict):
            continue
        provider = _provider_for_saved_secret(providers, str(raw_key), item)
        matched = provider is not None
        rows.append(
            {
                "编号": _positive_int(provider.get("sort_order"), len(rows) + 1) if matched else "",
                "Provider": (provider.get("name") if matched else item.get("provider_name")) or str(raw_key),
                "模型": (provider.get("model") if matched else item.get("model")) or "",
                "Key": masked_secret(str(item.get("api_key") or "")),
                "更新时间": str(item.get("updated_at") or ""),
                "匹配状态": "已匹配当前 Provider" if matched else "未匹配当前 Provider",
                "保存标识": str(item.get("provider_key") or raw_key),
            }
        )
    return rows


def _provider_for_saved_secret(providers: list[dict], saved_key: str, item: dict) -> dict | None:
    for provider in providers:
        provider_key = str(provider.get("provider_key") or "")
        item_key = str(item.get("provider_key") or saved_key)
        if saved_key == provider_key or item_key == provider_key:
            return provider
    for provider in providers:
        if _saved_secret_matches_provider(saved_key, item, provider):
            return provider
    return None


def _saved_secret_for_provider(provider: dict, data: dict) -> tuple[str | None, dict | None]:
    saved = data.get("providers", {}) or {}
    provider_key = str(provider.get("provider_key") or "")
    for raw_key, item in saved.items():
        if not isinstance(item, dict):
            continue
        item_key = str(item.get("provider_key") or raw_key)
        if str(raw_key) == provider_key or item_key == provider_key:
            return str(raw_key), item
    for raw_key, item in saved.items():
        if isinstance(item, dict) and _saved_secret_matches_provider(str(raw_key), item, provider):
            return str(raw_key), item
    return None, None


def _saved_secret_matches_provider(saved_key: str, item: dict, provider: dict) -> bool:
    provider_name = _normalize_match_value(provider.get("name"))
    item_name = _normalize_match_value(item.get("provider_name"))
    if item_name and item_name == provider_name:
        return True

    item_model = _normalize_match_value(item.get("model"))
    provider_model = _normalize_match_value(provider.get("model"))
    item_type = _normalize_match_value(item.get("provider_type"))
    provider_type = _normalize_match_value(provider.get("provider_type"))
    item_base = _normalize_match_url(item.get("base_url"))
    provider_base = _normalize_match_url(provider.get("base_url"))

    if item_model and item_model == provider_model and item_type == provider_type and item_base and item_base == provider_base:
        return True
    return False


def _normalize_match_value(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_match_url(value: object) -> str:
    return _normalize_match_value(value).rstrip("/")


def _lock_secret_vault(providers: list[dict]) -> None:
    for key in ["secret_vault_unlocked", "secret_vault_data", "secret_vault_master_password"]:
        st.session_state.pop(key, None)
    for provider in providers:
        st.session_state.pop(f"api_key_provider_{provider['provider_key']}", None)


def _render_help() -> None:
    st.markdown(
        """
### 常见填写方式

**OpenAI Responses**
- Provider 类型：OpenAI Responses API
- Base URL：`https://api.openai.com/v1`
- 鉴权：`Authorization: Bearer <key>`
- 响应路径：`output_text`

**OpenAI 兼容代理，例如 CLIProxyAPI、One API、LiteLLM**
- Provider 类型：OpenAI 兼容 Chat Completions
- Base URL：`http://localhost:8317/v1`
- API Key：本地代理配置的客户端 Key，例如 `local-client-key`
- 响应路径：`choices.0.message.content`

**243706.xyz / Sub2API**
- Provider 类型：OpenAI 兼容 Chat Completions
- Base URL：`https://api.243706.xyz/v1`
- 模型：`gpt-5.4`
- API Key 环境变量：`SUB2API_KEY`
- 响应路径：`choices.0.message.content`

**Anthropic**
- Provider 类型：Anthropic Messages API
- Base URL：`https://api.anthropic.com`
- 鉴权：`x-api-key`
- 额外请求头：`{"anthropic-version":"2023-06-01"}`
- 响应路径：`content.0.text`

**Gemini**
- Provider 类型：Google Gemini generateContent
- Base URL：`https://generativelanguage.googleapis.com`
- 鉴权：`URL 查询参数 ?key=<key>`
- 响应路径：`candidates.0.content.parts.0.text`

**MiniMax**
- Provider 类型：MiniMax Chat API
- Base URL：`https://api.minimax.chat/v1`
- 鉴权：`Authorization: Bearer <key>`
- 响应路径：`choices.0.message.content`

**MIMO Token Plan**
- Provider 类型：OpenAI 兼容 Chat Completions
- Base URL：`https://token-plan-cn.xiaomimimo.com/v1`
- 可选集群：`https://token-plan-sgp.xiaomimimo.com/v1`、`https://token-plan-ams.xiaomimimo.com/v1`
- 模型：`mimo-v2.5-pro`
- 鉴权：`api-key: <tp-...>`
- 响应路径：`choices.0.message.content`

**自定义 HTTP JSON**
- Base URL / Endpoint 填完整 POST 地址。
- 请求体模板必须是 JSON。
- 可用变量：`{prompt}`、`{model}`、`{max_output_tokens}`。
"""
    )
    st.code(_default_custom_template(), language="json")


def _default_custom_template() -> str:
    return """{
  "model": "{model}",
  "messages": [
    {
      "role": "user",
      "content": "{prompt}"
    }
  ],
  "max_tokens": {max_output_tokens}
}"""


def _pretty_json(value: str) -> str:
    try:
        return json.dumps(json.loads(value or "{}"), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return value or "{}"


def _index_or_zero(values: list[str], selected: str | None) -> int:
    try:
        return values.index(selected or "")
    except ValueError:
        return 0


def _positive_int(value: object, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default
