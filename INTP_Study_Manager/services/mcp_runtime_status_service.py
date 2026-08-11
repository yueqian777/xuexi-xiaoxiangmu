from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any

import db


RUNTIME_SETTING_NAME = "mcp_runtime_status"
RUNTIME_VERSION = 2
SUPPORTED_TRANSPORTS = frozenset({"stdio"})


class RuntimeStatusStorageError(RuntimeError):
    """Raised when a namespaced runtime record belongs to another user."""


def runtime_status_setting_key(user_id: int) -> str:
    return f"user:{_normalize_user_id(user_id)}:{RUNTIME_SETTING_NAME}"


def mark_runtime_started(
    user_id: int,
    *,
    pid: int | None = None,
    transport: str = "stdio",
) -> dict[str, Any]:
    """Record only the local process metadata needed by the status page."""

    user_id_int = _normalize_user_id(user_id)
    pid_int = _normalize_pid(os.getpid() if pid is None else pid)
    transport_value = _normalize_transport(transport)
    key = runtime_status_setting_key(user_id_int)
    db.init_db()
    with db.write_transaction() as conn:
        _assert_key_owner(conn, key, user_id_int)
        timestamp = _database_timestamp(conn)
        payload = {
            "pid": pid_int,
            "transport": transport_value,
            "started_at": timestamp,
            "stopped_at": None,
            "process_identity": _process_identity(pid_int),
            "runtime_version": RUNTIME_VERSION,
        }
        _upsert_payload(conn, key, user_id_int, payload, timestamp)
    return _status_from_payload(payload)


def mark_runtime_stopped(
    user_id: int,
    *,
    pid: int | None = None,
) -> dict[str, Any]:
    """Mark the recorded process stopped without retaining command lines or secrets."""

    user_id_int = _normalize_user_id(user_id)
    pid_int = _normalize_pid(os.getpid() if pid is None else pid)
    key = runtime_status_setting_key(user_id_int)
    db.init_db()
    with db.write_transaction() as conn:
        _assert_key_owner(conn, key, user_id_int)
        payload = _load_payload(conn, key, user_id_int)
        if payload is None:
            return _empty_status()
        if int(payload["pid"]) != pid_int:
            return _status_from_payload(payload)
        if payload.get("stopped_at"):
            return _status_from_payload(payload)
        timestamp = _database_timestamp(conn)
        payload["stopped_at"] = timestamp
        _upsert_payload(conn, key, user_id_int, payload, timestamp)
    return _status_from_payload(payload)


def get_runtime_status(user_id: int) -> dict[str, Any]:
    """Return running/stopped/stale state for exactly one user's local stdio process."""

    user_id_int = _normalize_user_id(user_id)
    key = runtime_status_setting_key(user_id_int)
    db.init_db()
    with db.managed_connection() as conn:
        payload = _load_payload(conn, key, user_id_int)
    return _status_from_payload(payload) if payload else _empty_status()


def _empty_status() -> dict[str, Any]:
    return {
        "configured": False,
        "running": False,
        "state": "never_started",
        "pid": None,
        "transport": None,
        "started_at": None,
        "stopped_at": None,
        "identity_verified": False,
        "runtime_version": RUNTIME_VERSION,
    }


def _status_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stopped_at = payload.get("stopped_at")
    pid = int(payload["pid"])
    pid_alive = bool(not stopped_at and _is_pid_running(pid))
    stored_identity = payload.get("process_identity")
    current_identity = _process_identity(pid) if pid_alive else None
    identity_verified = bool(
        stored_identity
        and current_identity
        and stored_identity == current_identity
    )
    running = bool(pid_alive and identity_verified)
    if stopped_at:
        state = "stopped"
    elif running:
        state = "running"
    elif pid_alive and not stored_identity:
        state = "unverified"
    else:
        state = "stale"
    return {
        "configured": True,
        "running": running,
        "state": state,
        "pid": int(payload["pid"]),
        "transport": str(payload["transport"]),
        "started_at": str(payload.get("started_at") or ""),
        "stopped_at": str(stopped_at) if stopped_at else None,
        "identity_verified": identity_verified,
        "runtime_version": RUNTIME_VERSION,
    }


def _load_payload(conn, key: str, user_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ? AND user_id = ?",
        (key, user_id),
    ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["value"] or "")
        pid = _normalize_pid(payload.get("pid"))
        transport = _normalize_transport(payload.get("transport"))
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    started_at = str(payload.get("started_at") or "").strip()
    if not started_at:
        return None
    stopped_at = payload.get("stopped_at")
    process_identity = payload.get("process_identity")
    if process_identity is not None and (
        not isinstance(process_identity, str) or len(process_identity) > 128
    ):
        return None
    return {
        "pid": pid,
        "transport": transport,
        "started_at": started_at,
        "stopped_at": str(stopped_at).strip() if stopped_at else None,
        "process_identity": process_identity or None,
        "runtime_version": RUNTIME_VERSION,
    }


def _assert_key_owner(conn, key: str, user_id: int) -> None:
    row = conn.execute(
        "SELECT user_id FROM app_settings WHERE key = ?",
        (key,),
    ).fetchone()
    if row and int(row["user_id"]) != user_id:
        raise RuntimeStatusStorageError("MCP runtime 状态的用户范围发生冲突。")


def _upsert_payload(
    conn,
    key: str,
    user_id: int,
    payload: dict[str, Any],
    timestamp: str,
) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, user_id, value, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        WHERE app_settings.key = excluded.key
          AND app_settings.user_id = excluded.user_id
        """,
        (key, user_id, json.dumps(payload, sort_keys=True), timestamp),
    )


def _database_timestamp(conn) -> str:
    row = conn.execute("SELECT datetime('now', 'localtime') AS value").fetchone()
    return str(row["value"] or "")


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


def _normalize_pid(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("PID 必须是正整数。")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("PID 必须是正整数。") from exc
    if normalized <= 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValueError("PID 必须是正整数。")
    return normalized


def _normalize_transport(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in SUPPORTED_TRANSPORTS:
        raise ValueError("当前只支持 stdio transport。")
    return normalized


def _is_pid_running(pid: int) -> bool:
    """Probe a process without sending a signal that could terminate it on Windows."""

    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and (
                int(exit_code.value) == still_active
            )
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _process_identity(pid: int) -> str | None:
    """Return an OS process-creation identity so PID reuse is not trusted."""

    if pid <= 0:
        return None
    if os.name == "nt":
        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return None
            value = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
            return f"win-filetime:{value}"
        finally:
            kernel32.CloseHandle(handle)

    stat_path = Path(f"/proc/{pid}/stat")
    try:
        stat = stat_path.read_text(encoding="utf-8")
        fields_after_name = stat[stat.rfind(")") + 2 :].split()
        start_ticks = fields_after_name[19]
    except (OSError, IndexError, ValueError):
        return None
    return f"proc-start-ticks:{start_ticks}"
