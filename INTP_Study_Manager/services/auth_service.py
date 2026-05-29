from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import db


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    display_name: str
    role: str


def get_current_user() -> CurrentUser:
    return _single_existing_user() or _default_local_user()


def require_login() -> CurrentUser:
    return get_current_user()


def require_admin() -> CurrentUser:
    return require_login()


def get_user_upload_usage(user_id: int) -> dict[str, int]:
    total = 0
    try:
        rows = db.fetch_all("SELECT file_path FROM ppt_decks WHERE user_id = ?", (int(user_id),))
    except sqlite3.Error:
        rows = []
    for row in rows:
        path_text = str(row.get("file_path") or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        if path.exists() and path.is_file():
            total += path.stat().st_size
    return {"used_bytes": total, "quota_bytes": 0}


def format_bytes(value: int) -> str:
    if int(value) == 0:
        return "无限制"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(0, int(value)))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{int(value)} B"


def _default_local_user() -> CurrentUser:
    return CurrentUser(id=0, username="local", display_name="本地用户", role="admin")


def _single_existing_user() -> CurrentUser | None:
    try:
        with db.managed_connection() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            if not columns:
                return None
            where = "WHERE COALESCE(is_active, 1) = 1" if "is_active" in columns else ""
            rows = conn.execute(
                f"""
                SELECT id, username, display_name, role
                FROM users
                {where}
                ORDER BY id ASC
                """
            ).fetchall()
    except sqlite3.Error:
        return None
    if len(rows) != 1:
        return None
    row = dict(rows[0])
    user_id = int(row.get("id") or 0)
    username = str(row.get("username") or f"user_{user_id}")
    display_name = str(row.get("display_name") or username)
    return CurrentUser(id=user_id, username=username, display_name=display_name, role="admin")
