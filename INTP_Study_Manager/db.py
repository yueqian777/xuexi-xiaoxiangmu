from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "study_manager.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                subject TEXT NOT NULL,
                chapter TEXT DEFAULT '',
                title TEXT NOT NULL,
                main_question TEXT NOT NULL,
                mastered_content TEXT DEFAULT '',
                blockers TEXT DEFAULT '',
                wrong_questions TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                mastery INTEGER NOT NULL DEFAULT 0,
                need_review INTEGER NOT NULL DEFAULT 1,
                is_key INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS mainline_anchors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                anchor_code TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                order_index INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES study_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS branch_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                anchor_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer_summary TEXT DEFAULT '',
                understood INTEGER NOT NULL DEFAULT 0,
                need_review INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (session_id) REFERENCES study_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (anchor_id) REFERENCES mainline_anchors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                core_question TEXT DEFAULT '',
                one_sentence TEXT NOT NULL,
                logic_or_formula TEXT DEFAULT '',
                application TEXT DEFAULT '',
                mastery INTEGER NOT NULL DEFAULT 0,
                need_review INTEGER NOT NULL DEFAULT 1,
                source_session_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (source_session_id) REFERENCES study_sessions(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                knowledge_id INTEGER,
                original_question TEXT NOT NULL,
                my_wrong_answer TEXT DEFAULT '',
                correct_idea TEXT NOT NULL,
                cause_category TEXT NOT NULL,
                warning_signal TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                add_to_review INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (knowledge_id) REFERENCES knowledge_cards(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS review_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_id INTEGER NOT NULL,
                review_date TEXT NOT NULL,
                review_stage TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '待复习',
                result TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (knowledge_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS parking_lot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT DEFAULT '',
                question TEXT NOT NULL,
                source TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT '未解决',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS ppt_decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                title TEXT NOT NULL,
                subject TEXT DEFAULT '',
                file_path TEXT NOT NULL,
                slide_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS ppt_slides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL,
                slide_number INTEGER NOT NULL,
                title TEXT DEFAULT '',
                slide_text TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE,
                UNIQUE(deck_id, slide_number)
            );

            CREATE TABLE IF NOT EXISTS slide_explanations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slide_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                explanation TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (slide_id) REFERENCES ppt_slides(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS slide_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slide_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (slide_id) REFERENCES ppt_slides(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS api_providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                provider_type TEXT NOT NULL,
                base_url TEXT DEFAULT '',
                model TEXT DEFAULT '',
                api_key_env TEXT DEFAULT '',
                auth_type TEXT NOT NULL DEFAULT 'bearer',
                extra_headers_json TEXT DEFAULT '{}',
                request_template_json TEXT DEFAULT '',
                response_path TEXT DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS daily_review_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_date TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT '已完成',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            """
        )
        _ensure_column(conn, "ppt_slides", "image_path", "TEXT DEFAULT ''")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def fetch_all(query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def fetch_one(query: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    return dict(row) if row else None


def execute(query: str, params: Iterable[Any] = ()) -> None:
    with get_connection() as conn:
        conn.execute(query, tuple(params))


def insert_and_get_id(query: str, params: Iterable[Any] = ()) -> int:
    with get_connection() as conn:
        cursor = conn.execute(query, tuple(params))
        return int(cursor.lastrowid)
