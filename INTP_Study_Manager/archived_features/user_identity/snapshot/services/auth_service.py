from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st

import db
from db import execute, fetch_all, fetch_one, write_transaction

CURRENT_USER_SESSION_KEY = "current_user"
AUTH_SESSION_COOKIE_NAME = "intp_study_auth"
AUTH_SESSION_TOKEN_KEY = "auth_session_token"
AUTH_SESSION_EXPIRES_AT_KEY = "auth_session_expires_at"
AUTH_SESSION_IDLE_SECONDS = 5 * 60
PASSWORD_SALT_PREFIX = "pbkdf2_sha256"


SENSITIVE_SESSION_PREFIXES = (
    "api_key_provider_",
    "api_model_provider_",
    "dashboard_api_key_",
    "balance_credential_",
    "ppt_provider_",
    "test_provider_",
    "ppt_reader_active_slide_",
    "ppt_reader_position_last_token_",
    "study_asset_task_",
    "study_asset_draft_",
    "study_asset_raw_",
    "study_asset_meta_",
)

SENSITIVE_SESSION_KEYS = {
    CURRENT_USER_SESSION_KEY,
    AUTH_SESSION_TOKEN_KEY,
    AUTH_SESSION_EXPIRES_AT_KEY,
    "secret_vault_unlocked",
    "secret_vault_data",
    "secret_vault_master_password",
    "active_api_provider_key",
    "active_api_model",
    "active_api_max_tokens",
    "active_api_reasoning_depth",
    "last_provider_balance_result",
    "ppt_reader_deck_id",
    "ppt_generation_task",
    "ppt_generation_last_refresh",
    "ppt_structure_task",
    "ppt_structure_last_refresh",
    "ppt_study_asset_last_refresh",
    "ppt_parallel_benchmark_results",
}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    display_name: str
    role: str


def ensure_auth_tables() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            upload_quota_bytes INTEGER NOT NULL DEFAULT 536870912,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS invites (
            code TEXT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'user',
            created_by INTEGER,
            max_uses INTEGER NOT NULL DEFAULT 1,
            used_count INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            upload_quota_bytes INTEGER NOT NULL DEFAULT 536870912,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            revoked_at INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_seen
        ON auth_sessions(user_id, last_seen_at DESC)
        """
    )
    _ensure_auth_column("users", "upload_quota_bytes", "INTEGER NOT NULL DEFAULT 536870912")
    _ensure_auth_column("invites", "upload_quota_bytes", "INTEGER NOT NULL DEFAULT 536870912")


def _ensure_auth_column(table: str, column: str, definition: str) -> None:
    row = fetch_one(f"PRAGMA table_info({table})")
    columns = {item['name'] for item in fetch_all(f"PRAGMA table_info({table})")}
    if column not in columns:
        execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def has_initialized_admin() -> bool:
    ensure_auth_tables()
    row = fetch_one(
        """
        SELECT id
        FROM users
        WHERE role = 'admin' AND is_active = 1 AND TRIM(COALESCE(password_hash, '')) != ''
        ORDER BY id ASC LIMIT 1
        """
    )
    return row is not None


def bootstrap_admin(*, username: str, password: str, display_name: str | None = None) -> int:
    ensure_auth_tables()
    username = username.strip()
    if not username.strip() or not password:
        raise ValueError("初始管理员账号和密码不能为空。")
    password_hash = hash_password(password)
    with write_transaction() as conn:
        existing = conn.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1").fetchone()
        if existing:
            return int(existing["id"])
        try:
            cursor = conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash, role)
                VALUES (?, ?, ?, 'admin')
                """,
                (username, display_name or username, password_hash),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在。") from exc
        return int(cursor.lastrowid)


def initialize_first_admin(username: str, password: str, *, display_name: str | None = None) -> int:
    ensure_auth_tables()
    username = username.strip()
    if not username:
        raise ValueError("管理员用户名不能为空。")
    if not password:
        raise ValueError("管理员密码不能为空。")
    password_hash = hash_password(password)
    with write_transaction() as conn:
        existing_admin = conn.execute(
            """
            SELECT id
            FROM users
            WHERE role = 'admin' AND is_active = 1 AND TRIM(COALESCE(password_hash, '')) != ''
            ORDER BY id ASC LIMIT 1
            """
        ).fetchone()
        if existing_admin:
            raise ValueError("系统已经存在可用管理员，无需再次初始化。")

        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row:
            conn.execute(
                """
                UPDATE users
                SET display_name = ?, password_hash = ?, role = 'admin', is_active = 1, updated_at = datetime('now', 'localtime')
                WHERE id = ?
                """,
                (display_name or username, password_hash, int(row["id"])),
            )
            return int(row["id"])
        cursor = conn.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role)
            VALUES (?, ?, ?, 'admin')
            """,
            (username, display_name or username, password_hash),
        )
        return int(cursor.lastrowid)


def create_user(username: str, password: str, *, display_name: str | None = None, role: str = "user", upload_quota_bytes: int = 536870912) -> int:
    ensure_auth_tables()
    username = username.strip()
    if not username:
        raise ValueError("用户名不能为空。")
    if not password:
        raise ValueError("密码不能为空。")
    password_hash = hash_password(password)
    with write_transaction() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash, role, upload_quota_bytes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, display_name or username, password_hash, role, int(upload_quota_bytes)),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在。") from exc
        return int(cursor.lastrowid)


def create_invite(*, role: str = "user", created_by: int | None = None, max_uses: int = 1, expires_in_days: int = 7, upload_quota_bytes: int = 536870912) -> str:
    ensure_auth_tables()
    code = secrets.token_urlsafe(16)
    expires_at = (datetime.now() + timedelta(days=expires_in_days)).isoformat(timespec="seconds") if expires_in_days > 0 else None
    execute(
        """
        INSERT INTO invites (code, role, created_by, max_uses, used_count, expires_at, upload_quota_bytes, is_active)
        VALUES (?, ?, ?, ?, 0, ?, ?, 1)
        """,
        (code, role, created_by, max_uses, expires_at, int(upload_quota_bytes)),
    )
    return code


def list_users() -> list[dict[str, Any]]:
    ensure_auth_tables()
    return fetch_all(
        """
        SELECT id, username, display_name, role, is_active, upload_quota_bytes, created_at, updated_at
        FROM users
        ORDER BY role DESC, id ASC
        """
    )


def set_user_active(user_id: int, is_active: bool) -> None:
    ensure_auth_tables()
    execute(
        """
        UPDATE users
        SET is_active = ?, updated_at = datetime('now', 'localtime')
        WHERE id = ?
        """,
        (int(bool(is_active)), int(user_id)),
    )


def set_user_upload_quota(user_id: int, upload_quota_bytes: int) -> None:
    ensure_auth_tables()
    execute(
        """
        UPDATE users
        SET upload_quota_bytes = ?, updated_at = datetime('now', 'localtime')
        WHERE id = ?
        """,
        (int(upload_quota_bytes), int(user_id)),
    )


def delete_user_and_data(user_id: int) -> None:
    ensure_auth_tables()
    target_user_id = int(user_id)
    file_paths: list[str] = []
    with write_transaction() as conn:
        user_row = conn.execute("SELECT role FROM users WHERE id = ?", (target_user_id,)).fetchone()
        if not user_row:
            return
        if str(user_row["role"] or "") == "admin":
            raise ValueError("不能删除管理员账户。")

        deck_rows = conn.execute("SELECT file_path FROM ppt_decks WHERE user_id = ?", (target_user_id,)).fetchall()
        image_rows = conn.execute("SELECT image_path FROM ppt_slides WHERE user_id = ?", (target_user_id,)).fetchall()
        file_paths = [
            str(row[column] or "").strip()
            for rows, column in ((deck_rows, "file_path"), (image_rows, "image_path"))
            for row in rows
            if str(row[column] or "").strip()
        ]

        for table in (
            "branch_questions",
            "mainline_anchors",
            "review_tasks",
            "mistakes",
            "knowledge_links",
            "knowledge_cards",
            "parking_lot",
            "slide_questions",
            "slide_explanations",
            "ppt_sections",
            "ppt_slides",
            "ppt_decks",
            "study_sessions",
            "daily_review_logs",
            "daily_ai_review_plans",
        ):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (target_user_id,))

        conn.execute("DELETE FROM invites WHERE created_by = ?", (target_user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (target_user_id,))

    secret_path = db.DATA_DIR / f"api_keys_user_{target_user_id}.enc.json"
    _safe_unlink_data_file(secret_path)
    for path_text in file_paths:
        _safe_unlink_data_file(path_text)


def get_user_upload_usage(user_id: int) -> dict[str, int]:
    ensure_auth_tables()
    user_row = fetch_one("SELECT role, upload_quota_bytes FROM users WHERE id = ?", (int(user_id),))
    role = str((user_row or {}).get("role") or "user")
    quota = 0 if role == "admin" else int((user_row or {}).get("upload_quota_bytes") or 0)
    total = 0
    for row in fetch_all("SELECT file_path FROM ppt_decks WHERE user_id = ?", (int(user_id),)):
        path_text = str(row.get("file_path") or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        if path.exists() and path.is_file():
            total += path.stat().st_size
    return {"used_bytes": total, "quota_bytes": quota}


def _safe_unlink_data_file(path_value: str | Path) -> bool:
    path_text = str(path_value or "").strip()
    if not path_text:
        return False
    path = Path(path_text)
    try:
        resolved_path = path.resolve(strict=False)
        data_root = db.DATA_DIR.resolve(strict=False)
    except OSError:
        return False
    if not _is_relative_to(resolved_path, data_root):
        return False
    if not resolved_path.exists() or not resolved_path.is_file():
        return False
    try:
        resolved_path.unlink()
    except OSError:
        return False
    return True


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def format_bytes(value: int) -> str:
    if int(value) == 0:
        return "无限制"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(0, int(value)))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024


def list_invites() -> list[dict[str, Any]]:
    ensure_auth_tables()
    return fetch_all(
        """
        SELECT i.code, i.role, i.max_uses, i.used_count, i.expires_at, i.upload_quota_bytes, i.is_active, i.created_at, i.updated_at, u.username AS created_by_name
        FROM invites i
        LEFT JOIN users u ON u.id = i.created_by
        ORDER BY i.created_at DESC
        """
    )


def set_invite_active(code: str, is_active: bool) -> None:
    ensure_auth_tables()
    execute(
        """
        UPDATE invites
        SET is_active = ?, updated_at = datetime('now', 'localtime')
        WHERE code = ?
        """,
        (int(bool(is_active)), code.strip()),
    )


def use_invite(code: str) -> dict[str, Any]:
    ensure_auth_tables()
    with write_transaction() as conn:
        invite = conn.execute("SELECT * FROM invites WHERE code = ?", (code.strip(),)).fetchone()
        if not invite:
            raise ValueError("邀请码不存在。")
        _validate_invite(dict(invite))
        conn.execute(
            """
            UPDATE invites
            SET used_count = used_count + 1,
                updated_at = datetime('now', 'localtime')
            WHERE code = ?
            """,
            (invite["code"],),
        )
        return dict(invite)


def _clear_sensitive_session_state() -> None:
    for key in list(st.session_state.keys()):
        if key in SENSITIVE_SESSION_KEYS:
            st.session_state.pop(key, None)
            continue
        if key.startswith(SENSITIVE_SESSION_PREFIXES):
            st.session_state.pop(key, None)


def _set_current_user_session(user: CurrentUser) -> None:
    st.session_state[CURRENT_USER_SESSION_KEY] = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


def login(username: str, password: str) -> CurrentUser:
    ensure_auth_tables()
    _clear_sensitive_session_state()
    row = fetch_one(
        """
        SELECT id, username, display_name, role, password_hash, is_active
        FROM users
        WHERE username = ?
        """,
        (username.strip(),),
    )
    if not row or not int(row["is_active"]):
        raise ValueError("用户名或密码错误。")
    if not verify_password(password, str(row["password_hash"] or "")):
        raise ValueError("用户名或密码错误。")
    user = CurrentUser(
        id=int(row["id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"] or row["username"]),
        role=str(row["role"] or "user"),
    )
    _set_current_user_session(user)
    _issue_device_session(user.id)
    return user


def register_by_invite(username: str, password: str, invite_code: str, *, display_name: str | None = None) -> CurrentUser:
    _clear_sensitive_session_state()
    ensure_auth_tables()
    username = username.strip()
    if not username:
        raise ValueError("用户名不能为空。")
    if not password:
        raise ValueError("密码不能为空。")
    password_hash = hash_password(password)
    with write_transaction() as conn:
        invite_row = conn.execute("SELECT * FROM invites WHERE code = ?", (invite_code.strip(),)).fetchone()
        if not invite_row:
            raise ValueError("邀请码不存在。")
        invite = dict(invite_row)
        _validate_invite(invite)
        try:
            cursor = conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash, role, upload_quota_bytes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    display_name or username,
                    password_hash,
                    str(invite["role"] or "user"),
                    int(invite.get("upload_quota_bytes") or 536870912),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在。") from exc
        conn.execute(
            """
            UPDATE invites
            SET used_count = used_count + 1,
                updated_at = datetime('now', 'localtime')
            WHERE code = ?
            """,
            (invite["code"],),
        )
        user = CurrentUser(
            id=int(cursor.lastrowid),
            username=username,
            display_name=display_name or username,
            role=str(invite["role"] or "user"),
        )
    _set_current_user_session(user)
    _issue_device_session(user.id)
    return user


def restore_current_user_from_device_session(*, now: int | None = None) -> CurrentUser | None:
    ensure_auth_tables()
    if get_current_user():
        return get_current_user()
    token = _browser_auth_token()
    if not token:
        return None
    user = _validate_device_session(token, now=now)
    if not user:
        _expire_browser_device_session()
        return None
    _set_current_user_session(user)
    _remember_browser_device_session(token, _unix_now(now) + AUTH_SESSION_IDLE_SECONDS)
    return user


def refresh_device_session_activity(*, now: int | None = None) -> CurrentUser | None:
    user = get_current_user()
    token = _browser_auth_token()
    if not user:
        return user
    if not token:
        _clear_sensitive_session_state()
        _expire_browser_device_session()
        return None
    now_value = _unix_now(now)
    token_hash = _auth_token_hash(token)
    with write_transaction() as conn:
        row = conn.execute(
            """
            SELECT s.token_hash, s.user_id, s.last_seen_at, s.revoked_at, u.username, u.display_name, u.role, u.is_active
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if (
            not row
            or int(row["user_id"]) != int(user.id)
            or int(row["is_active"]) != 1
            or row["revoked_at"] is not None
            or now_value - int(row["last_seen_at"]) > AUTH_SESSION_IDLE_SECONDS
        ):
            if row:
                conn.execute(
                    "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE token_hash = ?",
                    (now_value, token_hash),
                )
            _clear_sensitive_session_state()
            _expire_browser_device_session()
            return None
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (now_value, token_hash),
        )
    _remember_browser_device_session(token, now_value + AUTH_SESSION_IDLE_SECONDS)
    return user


def record_browser_activity_ping(token: str, *, activity_at: int | None = None, now: int | None = None) -> bool:
    if not token:
        return False
    now_value = _unix_now(now)
    activity_value = _normalize_client_activity_time(activity_at, now_value)
    token_hash = _auth_token_hash(token)
    with write_transaction() as conn:
        row = conn.execute(
            """
            SELECT s.last_seen_at, s.revoked_at, u.is_active
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if not row or int(row["is_active"]) != 1 or row["revoked_at"] is not None:
            return False
        last_seen_at = int(row["last_seen_at"])
        if activity_value - last_seen_at > AUTH_SESSION_IDLE_SECONDS and now_value - activity_value > AUTH_SESSION_IDLE_SECONDS:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE token_hash = ?",
                (now_value, token_hash),
            )
            return False
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (max(last_seen_at, min(activity_value, now_value)), token_hash),
        )
    return True


def get_current_user() -> CurrentUser | None:
    raw = st.session_state.get(CURRENT_USER_SESSION_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        return CurrentUser(
            id=int(raw["id"]),
            username=str(raw["username"]),
            display_name=str(raw["display_name"]),
            role=str(raw["role"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def require_login() -> CurrentUser:
    user = get_current_user()
    if not user:
        raise PermissionError("请先登录。")
    return user


def require_admin() -> CurrentUser:
    user = require_login()
    if user.role != "admin":
        raise PermissionError("需要管理员权限。")
    return user


def logout() -> None:
    token = _browser_auth_token()
    if token:
        revoke_device_session(token)
    _clear_sensitive_session_state()
    _expire_browser_device_session()


def revoke_device_session(token: str) -> None:
    if not token:
        return
    execute(
        """
        UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, ?)
        WHERE token_hash = ?
        """,
        (_unix_now(), _auth_token_hash(token)),
    )


def _issue_device_session(user_id: int, *, now: int | None = None) -> str:
    now_value = _unix_now(now)
    token = secrets.token_urlsafe(32)
    execute(
        """
        INSERT INTO auth_sessions (token_hash, user_id, created_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        (_auth_token_hash(token), int(user_id), now_value, now_value),
    )
    _remember_browser_device_session(token, now_value + AUTH_SESSION_IDLE_SECONDS)
    return token


def _validate_device_session(token: str, *, now: int | None = None) -> CurrentUser | None:
    now_value = _unix_now(now)
    token_hash = _auth_token_hash(token)
    with write_transaction() as conn:
        row = conn.execute(
            """
            SELECT s.token_hash, s.user_id, s.last_seen_at, s.revoked_at, u.username, u.display_name, u.role, u.is_active
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if not row or int(row["is_active"]) != 1 or row["revoked_at"] is not None:
            return None
        if now_value - int(row["last_seen_at"]) > AUTH_SESSION_IDLE_SECONDS:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE token_hash = ?",
                (now_value, token_hash),
            )
            return None
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (now_value, token_hash),
        )
    return CurrentUser(
        id=int(row["user_id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"] or row["username"]),
        role=str(row["role"] or "user"),
    )


def _remember_browser_device_session(token: str, expires_at: int) -> None:
    st.session_state[AUTH_SESSION_TOKEN_KEY] = token
    st.session_state[AUTH_SESSION_EXPIRES_AT_KEY] = int(expires_at)


def _expire_browser_device_session() -> None:
    st.session_state.pop(AUTH_SESSION_TOKEN_KEY, None)
    st.session_state[AUTH_SESSION_EXPIRES_AT_KEY] = 0


def _browser_auth_token() -> str:
    token = str(st.session_state.get(AUTH_SESSION_TOKEN_KEY) or "").strip()
    if token:
        return token
    try:
        return str(st.context.cookies.get(AUTH_SESSION_COOKIE_NAME) or "").strip()
    except Exception:
        return ""


def _auth_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unix_now(now: int | None = None) -> int:
    return int(time.time() if now is None else now)


def _normalize_client_activity_time(activity_at: int | None, now_value: int) -> int:
    if activity_at is None:
        return now_value
    try:
        value = int(activity_at)
    except (TypeError, ValueError):
        return now_value
    if value > 10_000_000_000:
        value //= 1000
    if value > now_value + 30:
        return now_value
    return max(0, value)


def _validate_invite(invite: dict[str, Any]) -> None:
    if not int(invite["is_active"]):
        raise ValueError("邀请码已停用。")
    if invite["expires_at"] and datetime.fromisoformat(str(invite["expires_at"])) < datetime.now():
        raise ValueError("邀请码已过期。")
    if int(invite["used_count"] or 0) >= int(invite["max_uses"] or 1):
        raise ValueError("邀请码使用次数已满。")


def get_user(user_id: int) -> CurrentUser | None:
    row = fetch_one(
        "SELECT id, username, display_name, role FROM users WHERE id = ?",
        (user_id,),
    )
    if not row:
        return None
    return CurrentUser(
        id=int(row["id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"] or row["username"]),
        role=str(row["role"] or "user"),
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return f"{PASSWORD_SALT_PREFIX}${salt.hex()}${derived.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        prefix, salt_hex, derived_hex = password_hash.split("$", 2)
    except ValueError:
        return False
    if prefix != PASSWORD_SALT_PREFIX:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(derived_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return hmac.compare_digest(expected, actual)
