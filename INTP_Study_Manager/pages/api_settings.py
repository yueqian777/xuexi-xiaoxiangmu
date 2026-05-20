from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from services.ai_service import (
    AIServiceError,
    DEFAULT_MODEL,
    PROVIDER_TYPES,
    generate_text,
    list_api_providers,
    provider_label,
    save_api_provider,
)
from services.api_key_ui import render_local_secret_unlock
from services.api_runtime import ensure_provider_model, provider_model_state_key
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
    st.title("API 接入设置")
    st.caption("统一管理模型接口：OpenAI、OpenAI 兼容代理、Anthropic、Gemini，以及任意自定义 HTTP JSON API。")

    providers = list_api_providers()
    if providers:
        st.subheader("当前 Provider")
        st.dataframe(
            pd.DataFrame(providers)[
                [
                    "id",
                    "name",
                    "provider_type",
                    "base_url",
                    "model",
                    "api_key_env",
                    "auth_type",
                    "enabled",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("暂无 Provider。应用启动时会自动创建默认模板。")

    tab_edit, tab_custom, tab_vault, tab_test, tab_help = st.tabs(
        ["编辑 Provider", "新增自定义 API", "加密 API Key", "测试调用", "填写参考"]
    )

    with tab_edit:
        _render_edit_provider(providers)

    with tab_custom:
        _render_create_provider()

    with tab_vault:
        _render_secret_vault(providers)

    with tab_test:
        _render_test_provider(providers)

    with tab_help:
        _render_help()


def _render_edit_provider(providers: list[dict]) -> None:
    if not providers:
        st.warning("没有可编辑的 Provider。")
        return
    provider_id = st.selectbox(
        "选择要编辑的 Provider",
        [p["id"] for p in providers],
        format_func=lambda item_id: provider_label(next(p for p in providers if p["id"] == item_id)),
    )
    provider = next(p for p in providers if p["id"] == provider_id)
    _provider_form("更新 Provider", provider, provider_id)


def _render_create_provider() -> None:
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
    }
    _provider_form("创建 Provider", provider, None)


def _provider_form(title: str, provider: dict, provider_id: int | None) -> None:
    with st.form(f"provider_form_{provider_id or 'new'}"):
        st.subheader(title)
        cols = st.columns(2)
        name = cols[0].text_input("名称", value=provider.get("name", ""))
        provider_type = cols[1].selectbox(
            "Provider 类型",
            list(PROVIDER_TYPES.keys()),
            index=_index_or_zero(list(PROVIDER_TYPES.keys()), provider.get("provider_type")),
            format_func=lambda value: PROVIDER_TYPES[value],
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
        saved_id = save_api_provider(
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
            },
            provider_id,
        )
    except Exception as exc:
        st.error(f"保存失败：{exc}")
        return
    st.success(f"Provider 已保存：#{saved_id}")
    st.rerun()


def _render_test_provider(providers: list[dict]) -> None:
    enabled = [p for p in providers if p["enabled"]]
    if not enabled:
        st.warning("没有启用的 Provider。")
        return

    provider_id = st.selectbox(
        "选择测试 Provider",
        [p["id"] for p in enabled],
        format_func=lambda item_id: provider_label(next(p for p in enabled if p["id"] == item_id)),
        key="test_provider_id",
    )
    provider = next(p for p in enabled if p["id"] == provider_id)
    key_name = f"api_key_provider_{provider_id}"
    ensure_provider_model(provider)
    model = st.text_input(
        "当前 API 临时模型",
        key=provider_model_state_key(provider_id),
        help="这个模型跟随当前 Provider 保存；切换测试 API 后会恢复该 API 自己的临时模型。",
    )
    active_model = model.strip() or provider.get("model") or DEFAULT_MODEL
    render_local_secret_unlock(
        provider,
        model=active_model,
        target_session_key=key_name,
        key_prefix=f"test_provider_{provider_id}",
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
                    provider_id=provider_id,
                    api_key=api_key,
                    model_override=active_model,
                    max_output_tokens=int(max_tokens),
                )
            st.success("调用成功。")
            st.markdown(output)
        except AIServiceError as exc:
            st.error(str(exc))


def _render_secret_vault(providers: list[dict]) -> None:
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

    rows = []
    for provider in providers:
        secret = get_provider_secret(data, int(provider["id"]))
        rows.append(
            {
                "id": provider["id"],
                "Provider": provider["name"],
                "模型": provider.get("model") or "",
                "Key": masked_secret(secret),
                "更新时间": saved.get(str(provider["id"]), {}).get("updated_at", ""),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    provider_id = st.selectbox(
        "选择要保存 / 更新 Key 的 Provider",
        [p["id"] for p in providers],
        format_func=lambda item_id: provider_label(next(p for p in providers if p["id"] == item_id)),
        key="secret_provider_id",
    )
    provider = next(p for p in providers if p["id"] == provider_id)
    current_secret = get_provider_secret(data, int(provider_id))
    with st.form("save_provider_secret"):
        api_key = st.text_input(
            "API Key",
            type="password",
            placeholder=f"当前：{masked_secret(current_secret)}；留空不会保存",
        )
        submitted = st.form_submit_button("加密保存这个 API Key", type="primary")

    if submitted:
        try:
            updated = upsert_provider_secret(
                data,
                provider_id=int(provider_id),
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
        st.session_state[f"api_key_provider_{provider_id}"] = api_key.strip()
        st.success("API Key 已加密保存，并已应用到当前会话。")
        st.rerun()

    cols = st.columns(3)
    if cols[0].button("应用全部已保存 Key 到当前会话"):
        _apply_vault_to_session(providers, data)
        st.success("已应用到当前会话。")
    if cols[1].button("删除当前 Provider 的已保存 Key", disabled=not bool(current_secret)):
        updated = delete_provider_secret(data, int(provider_id))
        try:
            save_secret_store(st.session_state["secret_vault_master_password"], updated)
        except SecretStoreError as exc:
            st.error(str(exc))
            return
        st.session_state["secret_vault_data"] = updated
        st.session_state.pop(f"api_key_provider_{provider_id}", None)
        st.success("已删除当前 Provider 的加密 Key。")
        st.rerun()
    if cols[2].button("锁定并清除本次会话 Key"):
        _lock_secret_vault(providers)
        st.success("已锁定。")
        st.rerun()


def _apply_vault_to_session(providers: list[dict], data: dict) -> None:
    for provider in providers:
        secret = get_provider_secret(data, int(provider["id"]))
        if secret:
            st.session_state[f"api_key_provider_{provider['id']}"] = secret


def _lock_secret_vault(providers: list[dict]) -> None:
    for key in ["secret_vault_unlocked", "secret_vault_data", "secret_vault_master_password"]:
        st.session_state.pop(key, None)
    for provider in providers:
        st.session_state.pop(f"api_key_provider_{provider['id']}", None)


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
