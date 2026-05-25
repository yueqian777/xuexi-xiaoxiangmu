from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st

from db import execute, fetch_all, fetch_one, insert_and_get_id

CURRENT_USER_SESSION_KEY = "current_user"
PASSWORD_SALT_PREFIX = "pbkdf2_sha256"


SENSITIVE_SESSION_PREFIXES = (
    "api_key_provider_",
    "api_model_provider_",
    "dashboard_api_key_",
    "balance_credential_",
    "ppt_provider_",
    "test_provider_",
)

SENSITIVE_SESSION_KEYS = {
    CURRENT_USER_SESSION_KEY,
    "secret_vault_unlocked",
    "secret_vault_data",
    "secret_vault_master_password",
    "active_api_provider_key",
    "active_api_model",
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
    existing = fetch_one("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1")
    if existing:
        return int(existing["id"])
    if not username.strip() or not password:
        raise ValueError("初始管理员账号和密码不能为空。")
    return create_user(username.strip(), password, display_name=display_name or username.strip(), role="admin")


def initialize_first_admin(username: str, password: str, *, display_name: str | None = None) -> int:
    ensure_auth_tables()
    if has_initialized_admin():
        raise ValueError("系统已经存在可用管理员，无需再次初始化。")
    username = username.strip()
    if not username:
        raise ValueError("管理员用户名不能为空。")
    if not password:
        raise ValueError("管理员密码不能为空。")
    row = fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    password_hash = hash_password(password)
    if row:
        execute(
            """
            UPDATE users
            SET display_name = ?, password_hash = ?, role = 'admin', is_active = 1, updated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (display_name or username, password_hash, int(row["id"])),
        )
        return int(row["id"])
    return create_user(username, password, display_name=display_name or username, role="admin")


def create_user(username: str, password: str, *, display_name: str | None = None, role: str = "user", upload_quota_bytes: int = 536870912) -> int:
    ensure_auth_tables()
    username = username.strip()
    if not username:
        raise ValueError("用户名不能为空。")
    if not password:
        raise ValueError("密码不能为空。")
    if fetch_one("SELECT id FROM users WHERE username = ?", (username,)):
        raise ValueError("用户名已存在。")
    password_hash = hash_password(password)
    return insert_and_get_id(
        """
        INSERT INTO users (username, display_name, password_hash, role, upload_quota_bytes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, display_name or username, password_hash, role, int(upload_quota_bytes)),
    )


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
    if fetch_one("SELECT role FROM users WHERE id = ?", (int(user_id),)).get("role") == "admin":
        raise ValueError("不能删除管理员账户。")

    deck_rows = fetch_all("SELECT file_path FROM ppt_decks WHERE user_id = ?", (int(user_id),))
    image_rows = fetch_all("SELECT image_path FROM ppt_slides WHERE user_id = ?", (int(user_id),))

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
        "ppt_slides",
        "ppt_decks",
        "study_sessions",
        "daily_review_logs",
        "daily_ai_review_plans",
    ):
        execute(f"DELETE FROM {table} WHERE user_id = ?", (int(user_id),))

    execute("DELETE FROM invites WHERE created_by = ?", (int(user_id),))
    execute("DELETE FROM users WHERE id = ?", (int(user_id),))

    secret_path = Path(__import__('services.secret_store', fromlist=['_secret_store_path'])._secret_store_path(int(user_id)))
    if secret_path.exists():
        secret_path.unlink()

    for row in deck_rows + image_rows:
        path_text = str(row.get("file_path") or row.get("image_path") or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        if path.exists() and path.is_file():
            path.unlink()


def get_user_upload_usage(user_id: int) -> dict[str, int]:
    ensure_auth_tables()
    user_row = fetch_one("SELECT upload_quota_bytes FROM users WHERE id = ?", (int(user_id),))
    quota = int((user_row or {}).get("upload_quota_bytes") or 0)
    total = 0
    for row in fetch_all("SELECT file_path FROM ppt_decks WHERE user_id = ?", (int(user_id),)):
        path_text = str(row.get("file_path") or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        if path.exists() and path.is_file():
            total += path.stat().st_size
    return {"used_bytes": total, "quota_bytes": quota}


def format_bytes(value: int) -> str:
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
    invite = fetch_one("SELECT * FROM invites WHERE code = ?", (code.strip(),))
    if not invite:
        raise ValueError("邀请码不存在。")
    if not int(invite["is_active"]):
        raise ValueError("邀请码已停用。")
    if invite["expires_at"] and datetime.fromisoformat(str(invite["expires_at"])) < datetime.now():
        raise ValueError("邀请码已过期。")
    if int(invite["used_count"] or 0) >= int(invite["max_uses"] or 1):
        raise ValueError("邀请码使用次数已满。")
    execute(
        """
        UPDATE invites
        SET used_count = used_count + 1,
            updated_at = datetime('now', 'localtime')
        WHERE code = ?
        """,
        (invite["code"],),
    )
    return invite


def _clear_sensitive_session_state() -> None:
    for key in list(st.session_state.keys()):
        if key in SENSITIVE_SESSION_KEYS:
            st.session_state.pop(key, None)
            continue
        if key.startswith(SENSITIVE_SESSION_PREFIXES):
            st.session_state.pop(key, None)


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
    st.session_state[CURRENT_USER_SESSION_KEY] = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }
    return user


def register_by_invite(username: str, password: str, invite_code: str, *, display_name: str | None = None) -> CurrentUser:
    _clear_sensitive_session_state()
    invite = use_invite(invite_code)
    user_id = create_user(
        username,
        password,
        display_name=display_name or username.strip(),
        role=str(invite["role"] or "user"),
        upload_quota_bytes=int(invite.get("upload_quota_bytes") or 536870912),
    )
    user = get_user(user_id)
    if not user:
        raise ValueError("用户创建失败。")
    st.session_state[CURRENT_USER_SESSION_KEY] = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }
    return user


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
    _clear_sensitive_session_state()


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
