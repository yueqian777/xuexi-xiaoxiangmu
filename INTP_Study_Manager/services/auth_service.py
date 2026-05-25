from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import streamlit as st

from db import execute, fetch_all, fetch_one, insert_and_get_id

CURRENT_USER_SESSION_KEY = "current_user"
PASSWORD_SALT_PREFIX = "pbkdf2_sha256"


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
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )


def bootstrap_admin(*, username: str, password: str, display_name: str | None = None) -> int:
    ensure_auth_tables()
    existing = fetch_one("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1")
    if existing:
        return int(existing["id"])
    if not username.strip() or not password:
        raise ValueError("初始管理员账号和密码不能为空。")
    return create_user(username.strip(), password, display_name=display_name or username.strip(), role="admin")


def create_user(username: str, password: str, *, display_name: str | None = None, role: str = "user") -> int:
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
        INSERT INTO users (username, display_name, password_hash, role)
        VALUES (?, ?, ?, ?)
        """,
        (username, display_name or username, password_hash, role),
    )


def create_invite(*, role: str = "user", created_by: int | None = None, max_uses: int = 1, expires_in_days: int = 7) -> str:
    ensure_auth_tables()
    code = secrets.token_urlsafe(16)
    expires_at = (datetime.now() + timedelta(days=expires_in_days)).isoformat(timespec="seconds") if expires_in_days > 0 else None
    execute(
        """
        INSERT INTO invites (code, role, created_by, max_uses, used_count, expires_at, is_active)
        VALUES (?, ?, ?, ?, 0, ?, 1)
        """,
        (code, role, created_by, max_uses, expires_at),
    )
    return code


def list_users() -> list[dict[str, Any]]:
    ensure_auth_tables()
    return fetch_all(
        """
        SELECT id, username, display_name, role, is_active, created_at, updated_at
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


def list_invites() -> list[dict[str, Any]]:
    ensure_auth_tables()
    return fetch_all(
        """
        SELECT i.code, i.role, i.max_uses, i.used_count, i.expires_at, i.is_active, i.created_at, i.updated_at, u.username AS created_by_name
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


def login(username: str, password: str) -> CurrentUser:
    ensure_auth_tables()
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
    invite = use_invite(invite_code)
    user_id = create_user(username, password, display_name=display_name or username.strip(), role=str(invite["role"] or "user"))
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
    st.session_state.pop(CURRENT_USER_SESSION_KEY, None)


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
