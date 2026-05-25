from __future__ import annotations

from typing import Any

import streamlit as st

from services.secret_store import (
    CRYPTOGRAPHY_AVAILABLE,
    SecretStoreError,
    get_provider_secret,
    load_secret_public_index,
    load_secret_store,
    save_secret_store,
    secret_store_exists,
)


def render_local_secret_unlock(
    provider: dict[str, Any],
    *,
    model: str,
    target_session_key: str,
    key_prefix: str,
    widget_session_key: str | None = None,
) -> bool:
    candidates = find_local_secret_candidates(provider, model=model)
    if not candidates:
        return False

    if not CRYPTOGRAPHY_AVAILABLE:
        st.warning("检测到匹配的本地加密 API Key，但当前 Python 环境缺少 cryptography，无法解锁。")
        return False

    vault_data = _unlocked_secret_data()
    if vault_data:
        if _apply_best_secret(vault_data, candidates, provider, target_session_key, widget_session_key=widget_session_key):
            st.caption("已自动使用本次已解锁的本地加密 API Key。")
            return True
        decrypted_candidates = _find_decrypted_candidates(vault_data, provider, model)
        if decrypted_candidates and _apply_best_secret(vault_data, decrypted_candidates, provider, target_session_key, widget_session_key=widget_session_key):
            st.caption("已自动使用本次已解锁的本地加密 API Key。")
            return True
        return False

    with st.container(border=True):
        st.markdown("**检测到匹配的本地加密 API Key**")
        st.caption("输入一次主密码后，本次 Streamlit 会话会自动复用已解锁的 Key，不会明文写入数据库。")
        selected_provider_key = _render_candidate_select(candidates, key_prefix)

        master_password = st.text_input(
            "输入主密码以解锁",
            type="password",
            key=f"{key_prefix}_local_secret_password",
        )
        if st.button("解锁并使用本地 API Key", key=f"{key_prefix}_unlock_local_secret", type="primary"):
            _unlock_and_apply(master_password, selected_provider_key, target_session_key, widget_session_key=widget_session_key)
        return True


def has_matching_local_secret(provider: dict[str, Any], *, model: str) -> bool:
    return bool(find_local_secret_candidates(provider, model=model))


def find_local_secret_candidates(provider: dict[str, Any], *, model: str) -> list[dict[str, Any]]:
    if not secret_store_exists():
        return []

    candidates = _find_index_candidates(provider, model)
    vault_data = _unlocked_secret_data()
    if not candidates and vault_data:
        candidates = _find_decrypted_candidates(vault_data, provider, model)
    return candidates


def _unlock_and_apply(
    master_password: str,
    provider_key: str,
    target_session_key: str,
    *,
    widget_session_key: str | None = None,
) -> None:
    if not master_password:
        st.error("请输入主密码。")
        return
    try:
        data = load_secret_store(master_password)
    except SecretStoreError as exc:
        st.error(str(exc))
        return
    _refresh_public_index(master_password, data)
    st.session_state["secret_vault_unlocked"] = True
    st.session_state["secret_vault_data"] = data
    st.session_state["secret_vault_master_password"] = master_password
    if _apply_secret(data, provider_key, target_session_key, widget_session_key=widget_session_key):
        st.success("已应用本地加密 API Key 到当前会话。")
        st.rerun()


def _apply_secret(
    data: dict[str, Any],
    provider_key: str,
    target_session_key: str,
    *,
    widget_session_key: str | None = None,
    show_errors: bool = True,
) -> bool:
    secret = get_provider_secret(data, provider_key)
    if not secret:
        if show_errors:
            st.error("密钥库中没有找到这个 Provider 的 API Key。")
        return False
    st.session_state[target_session_key] = secret
    if widget_session_key:
        st.session_state[widget_session_key] = secret
    return True


def _apply_best_secret(
    data: dict[str, Any],
    candidates: list[dict[str, Any]],
    provider: dict[str, Any],
    target_session_key: str,
    *,
    widget_session_key: str | None = None,
) -> bool:
    if not candidates:
        return False
    ordered = [_best_candidate(candidates, provider)]
    ordered.extend(item for item in candidates if item is not ordered[0])
    for item in ordered:
        if _apply_secret(
            data,
            str(item["provider_key"]),
            target_session_key,
            widget_session_key=widget_session_key,
            show_errors=False,
        ):
            return True
    return False


def _best_candidate(candidates: list[dict[str, Any]], provider: dict[str, Any]) -> dict[str, Any]:
    current_provider_key = str(provider.get("provider_key") or "")
    for item in candidates:
        if str(item.get("provider_key") or "") == current_provider_key:
            return item
    return candidates[0]


def _render_candidate_select(candidates: list[dict[str, Any]], key_prefix: str) -> str:
    if len(candidates) == 1:
        item = candidates[0]
        st.caption(f"匹配到：{_candidate_label(item)}")
        return str(item["provider_key"])

    return str(
        st.selectbox(
            "选择本地 API Key",
            [item["provider_key"] for item in candidates],
            format_func=lambda item_key: _candidate_label(
                next(item for item in candidates if item["provider_key"] == item_key)
            ),
            key=f"{key_prefix}_local_secret_candidate",
        )
    )


def _unlocked_secret_data() -> dict[str, Any] | None:
    if not st.session_state.get("secret_vault_unlocked"):
        return None
    data = st.session_state.get("secret_vault_data")
    return data if isinstance(data, dict) else None


def _refresh_public_index(master_password: str, data: dict[str, Any]) -> None:
    try:
        save_secret_store(master_password, data)
    except SecretStoreError as exc:
        st.warning(f"密钥已解锁，但公开索引刷新失败：{exc}")


def _find_index_candidates(provider: dict[str, Any], model: str) -> list[dict[str, Any]]:
    candidates = []
    for item in load_secret_public_index():
        item = _normalize_public_item(item)
        score = _match_score(item, provider, model)
        if score <= 0:
            continue
        candidates.append({**item, "_score": score})
    candidates.sort(key=lambda item: (-int(item.get("_score", 0)), str(item.get("provider_name", ""))))
    return candidates


def _find_decrypted_candidates(data: dict[str, Any], provider: dict[str, Any], model: str) -> list[dict[str, Any]]:
    candidates = []
    for raw_key, item in data.get("providers", {}).items():
        if not isinstance(item, dict):
            continue
        public_item = {
            "provider_key": str(item.get("provider_key") or raw_key),
            "provider_name": str(item.get("provider_name") or ""),
            "model": str(item.get("model") or ""),
            "provider_type": str(item.get("provider_type") or ""),
            "base_url": str(item.get("base_url") or ""),
            "updated_at": str(item.get("updated_at") or ""),
        }
        score = _match_score(public_item, provider, model)
        if score > 0:
            candidates.append({**public_item, "_score": score})
    candidates.sort(key=lambda item: (-int(item.get("_score", 0)), str(item.get("provider_name", ""))))
    return candidates


def _match_score(item: dict[str, Any], provider: dict[str, Any], model: str) -> int:
    if str(item.get("provider_key") or "") == str(provider.get("provider_key") or ""):
        return 100

    item_model = _normalize(item.get("model"))
    current_model = _normalize(model or provider.get("model"))
    item_type = _normalize(item.get("provider_type"))
    current_type = _normalize(provider.get("provider_type"))
    item_base = _normalize_url(item.get("base_url"))
    current_base = _normalize_url(provider.get("base_url"))

    if item_model and item_model == current_model and item_type == current_type and item_base == current_base:
        return 80
    if item_model and item_model == current_model and item_type == current_type:
        return 60
    if item_model and item_model == current_model:
        return 40
    return 0


def _candidate_label(item: dict[str, Any]) -> str:
    parts = [
        item.get("provider_name") or "未命名 Provider",
        item.get("model") or "未记录模型",
    ]
    if item.get("updated_at"):
        parts.append(f"更新：{item['updated_at']}")
    return " · ".join(parts)


def _normalize_public_item(item: dict[str, Any]) -> dict[str, Any]:
    if "provider_key" in item:
        return item
    return {
        **item,
        "provider_key": str(item.get("provider_id") or ""),
    }


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_url(value: Any) -> str:
    return _normalize(value).rstrip("/")
