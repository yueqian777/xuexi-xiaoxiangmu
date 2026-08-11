from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import db


PERMISSION_SETTING_NAME = "mcp_permissions"

_DEFAULT_PERMISSIONS = {
    "read_current_context": True,
    "read_ppt": True,
    "read_question_tree": True,
    "read_knowledge_cards": True,
    "read_reviews": False,
    "write_slide_explanation": True,
    "write_slide_question": True,
    "write_knowledge_card": False,
    "write_review": False,
}
DEFAULT_PERMISSIONS = MappingProxyType(_DEFAULT_PERMISSIONS)
READ_PERMISSION_KEYS = frozenset(
    key for key in DEFAULT_PERMISSIONS if key.startswith("read_")
)
WRITE_PERMISSION_KEYS = frozenset(
    key for key in DEFAULT_PERMISSIONS if key.startswith("write_")
)
KNOWN_PERMISSION_KEYS = frozenset(DEFAULT_PERMISSIONS)


class PermissionStorageError(RuntimeError):
    """Raised when persisted MCP permissions cannot be trusted safely."""


class PermissionDeniedError(PermissionError):
    code = "permission_denied"

    def __init__(self, permission_key: str):
        self.permission_key = permission_key
        super().__init__(f"MCP 权限未开启：{permission_key}")


def permission_setting_key(user_id: int) -> str:
    return f"user:{_normalize_user_id(user_id)}:{PERMISSION_SETTING_NAME}"


def get_permissions(user_id: int) -> dict[str, bool]:
    """Return the effective local MCP permissions for exactly one user."""

    user_id_int = _normalize_user_id(user_id)
    key = permission_setting_key(user_id_int)
    db.init_db()
    row = db.fetch_one(
        "SELECT value FROM app_settings WHERE key = ? AND user_id = ?",
        (key, user_id_int),
    )
    if row is None:
        return dict(DEFAULT_PERMISSIONS)
    return _merge_stored_permissions(row.get("value"))


def update_permissions(
    user_id: int,
    updates: Mapping[str, bool],
) -> dict[str, bool]:
    """Validate and persist a partial set of permission overrides."""

    user_id_int = _normalize_user_id(user_id)
    normalized_updates = _validate_updates(updates)
    if not normalized_updates:
        return get_permissions(user_id_int)

    key = permission_setting_key(user_id_int)
    db.init_db()
    with db.write_transaction() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ? AND user_id = ?",
            (key, user_id_int),
        ).fetchone()
        effective = (
            _merge_stored_permissions(row["value"])
            if row is not None
            else dict(DEFAULT_PERMISSIONS)
        )
        effective.update(normalized_updates)
        payload = json.dumps(effective, ensure_ascii=False, sort_keys=True)
        cursor = conn.execute(
            """
            INSERT INTO app_settings (key, user_id, value, updated_at)
            VALUES (?, ?, ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            WHERE app_settings.key = excluded.key
              AND app_settings.user_id = excluded.user_id
            """,
            (key, user_id_int, payload),
        )
        if int(cursor.rowcount or 0) != 1:
            raise PermissionStorageError("MCP 权限设置的用户范围发生冲突。")
    return effective


def set_permission(user_id: int, permission_key: str, enabled: bool) -> dict[str, bool]:
    return update_permissions(user_id, {permission_key: enabled})


def set_permissions(
    user_id: int,
    updates: Mapping[str, bool],
) -> dict[str, bool]:
    """Stable adapter-facing alias for partial permission updates."""

    return update_permissions(user_id, updates)


def is_allowed(user_id: int, permission_key: str) -> bool:
    clean_key = _validate_permission_key(permission_key)
    return bool(get_permissions(user_id)[clean_key])


def is_permission_allowed(user_id: int, permission_key: str) -> bool:
    """Stable adapter-facing permission check."""

    return is_allowed(user_id, permission_key)


def require_permission(user_id: int, permission_key: str) -> None:
    clean_key = _validate_permission_key(permission_key)
    if not is_allowed(user_id, clean_key):
        raise PermissionDeniedError(clean_key)


def _merge_stored_permissions(raw_value: Any) -> dict[str, bool]:
    if not isinstance(raw_value, str) or not raw_value:
        raise PermissionStorageError("MCP 权限设置已损坏，本次操作已拒绝。")
    try:
        stored = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PermissionStorageError("MCP 权限设置已损坏，本次操作已拒绝。") from exc
    if not isinstance(stored, dict):
        raise PermissionStorageError("MCP 权限设置已损坏，本次操作已拒绝。")
    if not KNOWN_PERMISSION_KEYS.issubset(stored):
        raise PermissionStorageError("MCP 权限设置不完整，本次操作已拒绝。")

    effective = dict(DEFAULT_PERMISSIONS)
    for key, value in stored.items():
        if key not in KNOWN_PERMISSION_KEYS:
            continue
        if type(value) is not bool:
            raise PermissionStorageError("MCP 权限设置已损坏，本次操作已拒绝。")
        effective[key] = value
    return effective


def _validate_updates(updates: Mapping[str, bool]) -> dict[str, bool]:
    if not isinstance(updates, Mapping):
        raise ValueError("MCP 权限更新必须是对象。")
    normalized: dict[str, bool] = {}
    for key, enabled in updates.items():
        clean_key = _validate_permission_key(key)
        if type(enabled) is not bool:
            raise ValueError(f"MCP 权限 {clean_key} 必须使用真实布尔值。")
        normalized[clean_key] = enabled
    return normalized


def _validate_permission_key(permission_key: Any) -> str:
    if not isinstance(permission_key, str) or permission_key not in KNOWN_PERMISSION_KEYS:
        raise ValueError(f"未知 MCP 权限：{permission_key}")
    return permission_key


def _normalize_user_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("user_id 必须是非负整数。")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("user_id 必须是非负整数。") from exc
    if normalized < 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValueError("user_id 必须是非负整数。")
    return normalized
