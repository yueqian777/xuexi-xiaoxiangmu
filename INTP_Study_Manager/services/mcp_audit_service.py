from __future__ import annotations

import re
from typing import Any

import db


MAX_REQUEST_ID_CHARS = 128
MAX_TOOL_NAME_CHARS = 128
MAX_TARGET_TYPE_CHARS = 64
MAX_TARGET_ID_CHARS = 128
MAX_SUMMARY_CHARS = 300
MAX_RECENT_LOGS = 100

OPERATION_TYPES = frozenset({"READ", "WRITE"})
PERMISSION_RESULTS = frozenset({"allowed", "permission_denied"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_OPTIONAL_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]*$")


def record_audit_log(
    user_id: int,
    request_id: str | int,
    tool_name: str,
    operation_type: str,
    target_type: str = "",
    target_id: str | int = "",
    *,
    success: bool,
    permission_result: str,
    summary: str = "",
) -> int:
    """Persist bounded MCP metadata; content bodies are intentionally unsupported."""

    user_id_int = _normalize_user_id(user_id)
    clean_request_id = _required_identifier(
        request_id, "request_id", MAX_REQUEST_ID_CHARS
    )
    clean_tool_name = _required_identifier(
        tool_name, "tool_name", MAX_TOOL_NAME_CHARS
    )
    clean_operation_type = str(operation_type or "").strip().upper()
    if clean_operation_type not in OPERATION_TYPES:
        raise ValueError("operation_type 只能是 READ 或 WRITE。")
    clean_target_type = _optional_identifier(
        target_type, "target_type", MAX_TARGET_TYPE_CHARS
    )
    clean_target_id = _optional_identifier(
        target_id, "target_id", MAX_TARGET_ID_CHARS
    )
    if type(success) is not bool:
        raise ValueError("success 必须使用真实布尔值。")
    if permission_result not in PERMISSION_RESULTS:
        raise ValueError("permission_result 必须是 allowed 或 permission_denied。")
    clean_summary = _normalize_summary(summary)

    db.init_db()
    return db.insert_and_get_id(
        """
        INSERT INTO mcp_audit_logs (
            user_id, request_id, tool_name, operation_type, target_type,
            target_id, success, permission_result, summary
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id_int,
            clean_request_id,
            clean_tool_name,
            clean_operation_type,
            clean_target_type,
            clean_target_id,
            int(success),
            permission_result,
            clean_summary,
        ),
    )


def list_recent_audit_logs(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    user_id_int = _normalize_user_id(user_id)
    limit_int = _normalize_limit(limit)
    db.init_db()
    return db.fetch_all(
        """
        SELECT id, user_id, request_id, tool_name, operation_type, target_type,
               target_id, success, permission_result, summary, created_at
        FROM mcp_audit_logs
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_id_int, limit_int),
    )


def finalize_audit_log(
    user_id: int,
    audit_id: int,
    *,
    success: bool,
    permission_result: str,
    summary: str = "",
) -> bool:
    """Finalize one pre-created attempt without changing its identity or target."""

    user_id_int = _normalize_user_id(user_id)
    audit_id_int = _normalize_positive_int(audit_id, "audit_id")
    if type(success) is not bool:
        raise ValueError("success 必须使用真实布尔值。")
    if permission_result not in PERMISSION_RESULTS:
        raise ValueError("permission_result 必须是 allowed 或 permission_denied。")
    clean_summary = _normalize_summary(summary)
    db.init_db()
    with db.write_transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE mcp_audit_logs
            SET success = ?, permission_result = ?, summary = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                int(success),
                permission_result,
                clean_summary,
                audit_id_int,
                user_id_int,
            ),
        )
        return int(cursor.rowcount or 0) == 1


def _required_identifier(value: Any, field: str, max_chars: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field} 无效。")
    clean = str(value).strip()
    if not clean or len(clean) > max_chars or not _IDENTIFIER_RE.fullmatch(clean):
        raise ValueError(f"{field} 无效或超过 {max_chars} 个字符。")
    return clean


def _optional_identifier(value: Any, field: str, max_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field} 无效。")
    clean = str(value).strip()
    if len(clean) > max_chars or not _OPTIONAL_IDENTIFIER_RE.fullmatch(clean):
        raise ValueError(f"{field} 无效或超过 {max_chars} 个字符。")
    return clean


def _normalize_summary(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("summary 必须是简短文本。")
    clean = " ".join(value.split())
    if len(clean) > MAX_SUMMARY_CHARS:
        raise ValueError(f"summary 最多允许 {MAX_SUMMARY_CHARS} 个字符。")
    return clean


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


def _normalize_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit 必须是正整数。")
    if value <= 0 or value > MAX_RECENT_LOGS:
        raise ValueError(f"limit 必须在 1 到 {MAX_RECENT_LOGS} 之间。")
    return value


def _normalize_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} 必须是正整数。")
    return value
