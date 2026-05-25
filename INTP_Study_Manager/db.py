from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "study_manager.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def managed_connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with managed_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        _ensure_auth_tables(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
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
                user_id INTEGER NOT NULL DEFAULT 0,
                session_id INTEGER NOT NULL,
                anchor_code TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                order_index INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES study_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS branch_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
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
                user_id INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS knowledge_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                source_knowledge_id INTEGER NOT NULL,
                target_knowledge_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL DEFAULT '关联',
                relation_note TEXT DEFAULT '',
                compare_points TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (source_knowledge_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE,
                FOREIGN KEY (target_knowledge_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE,
                CHECK (source_knowledge_id != target_knowledge_id)
            );

            CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
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
                user_id INTEGER NOT NULL DEFAULT 0,
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
                user_id INTEGER NOT NULL DEFAULT 0,
                subject TEXT DEFAULT '',
                question TEXT NOT NULL,
                source TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT '未解决',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS ppt_decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                filename TEXT NOT NULL,
                title TEXT NOT NULL,
                subject TEXT DEFAULT '',
                category TEXT DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '使用中',
                file_path TEXT NOT NULL,
                slide_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS ppt_slides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
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
                user_id INTEGER NOT NULL DEFAULT 0,
                slide_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                explanation TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (slide_id) REFERENCES ppt_slides(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS slide_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                slide_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                model TEXT NOT NULL,
                category TEXT DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '未整理',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (slide_id) REFERENCES ppt_slides(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS api_providers (
                provider_key TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL UNIQUE,
                provider_type TEXT NOT NULL,
                base_url TEXT DEFAULT '',
                model TEXT DEFAULT '',
                api_key_env TEXT DEFAULT '',
                auth_type TEXT NOT NULL DEFAULT 'bearer',
                extra_headers_json TEXT DEFAULT '{}',
                request_template_json TEXT DEFAULT '',
                response_path TEXT DEFAULT '',
                balance_query_enabled INTEGER NOT NULL DEFAULT 0,
                balance_query_type TEXT NOT NULL DEFAULT 'auto_wallet',
                balance_query_config_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 0,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS daily_review_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                review_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '已完成',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(user_id, review_date)
            );

            CREATE TABLE IF NOT EXISTS daily_ai_review_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                review_date TEXT NOT NULL,
                provider_key TEXT,
                model TEXT DEFAULT '',
                plan_json TEXT NOT NULL DEFAULT '{}',
                source_snapshot_json TEXT NOT NULL DEFAULT '{}',
                answers_json TEXT DEFAULT '{}',
                evaluation_json TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT '待回答',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                evaluated_at TEXT DEFAULT '',
                UNIQUE(user_id, review_date),
                FOREIGN KEY (provider_key) REFERENCES api_providers(provider_key) ON DELETE SET NULL
            );
            """
        )
        _ensure_column(conn, "study_sessions", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "mainline_anchors", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "branch_questions", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "knowledge_cards", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "knowledge_links", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "mistakes", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "review_tasks", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "parking_lot", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "ppt_decks", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "ppt_slides", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "slide_explanations", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "slide_questions", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "api_providers", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "app_settings", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "daily_review_logs", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "daily_ai_review_plans", "user_id", "INTEGER NOT NULL DEFAULT 0")
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_study_sessions_user_date_id
                ON study_sessions(user_id, date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_study_sessions_user_subject_date_id
                ON study_sessions(user_id, subject, date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mainline_anchors_user_session_order
                ON mainline_anchors(user_id, session_id, order_index ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_branch_questions_user_anchor_created
                ON branch_questions(user_id, anchor_id, created_at ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_branch_questions_user_session_anchor
                ON branch_questions(user_id, session_id, anchor_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_user_mastery_created
                ON knowledge_cards(user_id, mastery ASC, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_user_subject_created
                ON knowledge_cards(user_id, subject, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_user_source_session
                ON knowledge_cards(user_id, source_session_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_links_user_source_created
                ON knowledge_links(user_id, source_knowledge_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_links_user_target_created
                ON knowledge_links(user_id, target_knowledge_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mistakes_user_knowledge_created
                ON mistakes(user_id, knowledge_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mistakes_user_subject_topic_created
                ON mistakes(user_id, subject, topic, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mistakes_user_subject_cause
                ON mistakes(user_id, subject, cause_category);
            CREATE INDEX IF NOT EXISTS idx_review_tasks_user_status_date_id
                ON review_tasks(user_id, status, review_date ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_review_tasks_user_knowledge_date
                ON review_tasks(user_id, knowledge_id, review_date ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_parking_lot_user_status_created
                ON parking_lot(user_id, status, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_ppt_decks_user_created
                ON ppt_decks(user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_slide_explanations_user_slide_created
                ON slide_explanations(user_id, slide_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_slide_questions_user_slide_created
                ON slide_questions(user_id, slide_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_daily_ai_review_plans_user_date
                ON daily_ai_review_plans(user_id, review_date DESC, id DESC);
            """
        )
        _migrate_api_provider_identity(conn)
        _migrate_daily_ai_review_plan_user_scope(conn)
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ppt_decks_manage
            ON ppt_decks(user_id, status, category, sort_order ASC, created_at DESC, id DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_slide_questions_manage
            ON slide_questions(user_id, status, category, sort_order ASC, created_at DESC, id DESC)
            """
        )
        conn.execute("DROP INDEX IF EXISTS idx_api_providers_enabled_id")
        conn.execute("DROP INDEX IF EXISTS idx_api_providers_enabled_order")
        conn.execute("DROP INDEX IF EXISTS idx_api_providers_order")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_providers_enabled_order
            ON api_providers(user_id, enabled, sort_order ASC, provider_key ASC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_providers_order
            ON api_providers(user_id, sort_order ASC, provider_key ASC)
            """
        )
        _migrate_default_users(conn)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_auth_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
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
    conn.execute(
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


def _migrate_default_users(conn: sqlite3.Connection) -> None:
    current_admin = conn.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1").fetchone()
    if not current_admin:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (username, display_name, password_hash, role, is_active)
            VALUES ('admin', '管理员', '', 'admin', 1)
            """
        )
    defaults = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    if not defaults:
        return
    default_user_id = int(defaults["id"])
    for table in (
        "study_sessions",
        "mainline_anchors",
        "branch_questions",
        "knowledge_cards",
        "knowledge_links",
        "mistakes",
        "review_tasks",
        "parking_lot",
        "ppt_decks",
        "ppt_slides",
        "slide_explanations",
        "slide_questions",
        "api_providers",
        "app_settings",
        "daily_review_logs",
        "daily_ai_review_plans",
    ):
        conn.execute(f"UPDATE {table} SET user_id = COALESCE(NULLIF(user_id, 0), ?)", (default_user_id,))


def _migrate_api_provider_identity(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "api_providers")
    if not columns or ("provider_key" in columns and "id" not in columns):
        return

    rows = conn.execute(
        """
        SELECT *
        FROM api_providers
        ORDER BY
            CASE WHEN sort_order <= 0 THEN 1 ELSE 0 END,
            sort_order ASC,
            name ASC
        """
    ).fetchall()
    old_id_to_key: dict[int, str] = {}
    used_keys: set[str] = set()
    provider_rows: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        provider_key = str(item.get("provider_key") or "").strip()
        if not provider_key:
            provider_key = _unique_provider_key(str(item.get("name") or "provider"), used_keys)
        else:
            provider_key = _dedupe_provider_key(provider_key, used_keys)
        item["provider_key"] = provider_key
        if item.get("id") is not None:
            old_id_to_key[int(item["id"])] = provider_key
        provider_rows.append(item)

    was_foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    _migrate_daily_ai_provider_identity(conn, old_id_to_key)
    conn.execute("DROP INDEX IF EXISTS idx_api_providers_enabled_id")
    conn.execute("DROP INDEX IF EXISTS idx_api_providers_enabled_order")
    conn.execute("DROP INDEX IF EXISTS idx_api_providers_order")
    conn.execute("ALTER TABLE api_providers RENAME TO api_providers_old_identity")
    conn.execute(_api_providers_schema_sql())
    conn.executemany(
        """
        INSERT INTO api_providers (
            provider_key, name, provider_type, base_url, model, api_key_env,
            auth_type, extra_headers_json, request_template_json, response_path,
            balance_query_enabled, balance_query_type, balance_query_config_json,
            enabled, sort_order, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                item["provider_key"],
                item.get("name") or "",
                item.get("provider_type") or "openai_chat",
                item.get("base_url") or "",
                item.get("model") or "",
                item.get("api_key_env") or "",
                item.get("auth_type") or "bearer",
                item.get("extra_headers_json") or "{}",
                item.get("request_template_json") or "",
                item.get("response_path") or "",
                int(item.get("balance_query_enabled") or 0),
                item.get("balance_query_type") or "auto_wallet",
                item.get("balance_query_config_json") or "{}",
                int(bool(item.get("enabled", 1))),
                int(item.get("sort_order") or 0),
                item.get("created_at") or "",
                item.get("updated_at") or "",
            )
            for item in provider_rows
        ),
    )
    conn.execute("DROP TABLE api_providers_old_identity")
    _migrate_default_api_config(conn, old_id_to_key)
    if was_foreign_keys_enabled:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_daily_ai_review_plan_user_scope(conn: sqlite3.Connection) -> None:
    indexes = conn.execute("PRAGMA index_list(daily_ai_review_plans)").fetchall()
    has_composite_unique = False
    for index in indexes:
        if not int(index["unique"]):
            continue
        cols = [row["name"] for row in conn.execute(f"PRAGMA index_info({index['name']})").fetchall()]
        if cols == ["user_id", "review_date"]:
            has_composite_unique = True
            break
    if has_composite_unique:
        return

    rows = conn.execute("SELECT * FROM daily_ai_review_plans ORDER BY id ASC").fetchall()
    conn.execute("DROP INDEX IF EXISTS idx_daily_ai_review_plans_date")
    conn.execute("DROP INDEX IF EXISTS idx_daily_ai_review_plans_user_date")
    conn.execute("ALTER TABLE daily_ai_review_plans RENAME TO daily_ai_review_plans_old_user_scope")
    conn.execute(_daily_ai_review_plans_schema_sql())
    conn.executemany(
        """
        INSERT INTO daily_ai_review_plans (
            id, user_id, review_date, provider_key, model, plan_json, source_snapshot_json,
            answers_json, evaluation_json, status, created_at, evaluated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                row["id"],
                int(row["user_id"] or 0),
                row["review_date"],
                row["provider_key"],
                row["model"] or "",
                row["plan_json"] or "{}",
                row["source_snapshot_json"] or "{}",
                row["answers_json"] or "{}",
                row["evaluation_json"] or "",
                row["status"] or "待回答",
                row["created_at"] or "",
                row["evaluated_at"] or "",
            )
            for row in rows
        ),
    )
    conn.execute("DROP TABLE daily_ai_review_plans_old_user_scope")


def _migrate_daily_ai_provider_identity(conn: sqlite3.Connection, old_id_to_key: dict[int, str]) -> None:
    columns = _table_columns(conn, "daily_ai_review_plans")
    if not columns or "provider_id" not in columns:
        return
    rows = conn.execute("SELECT * FROM daily_ai_review_plans ORDER BY id ASC").fetchall()
    conn.execute("DROP INDEX IF EXISTS idx_daily_ai_review_plans_date")
    conn.execute("ALTER TABLE daily_ai_review_plans RENAME TO daily_ai_review_plans_old_provider_identity")
    conn.execute(_daily_ai_review_plans_schema_sql())
    conn.executemany(
        """
        INSERT INTO daily_ai_review_plans (
            id, review_date, provider_key, model, plan_json, source_snapshot_json,
            answers_json, evaluation_json, status, created_at, evaluated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                row["id"],
                row["review_date"],
                old_id_to_key.get(int(row["provider_id"])) if row["provider_id"] is not None else None,
                row["model"] or "",
                row["plan_json"] or "{}",
                row["source_snapshot_json"] or "{}",
                row["answers_json"] or "{}",
                row["evaluation_json"] or "",
                row["status"] or "待回答",
                row["created_at"] or "",
                row["evaluated_at"] or "",
            )
            for row in rows
        ),
    )
    conn.execute("DROP TABLE daily_ai_review_plans_old_provider_identity")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_ai_review_plans_date
            ON daily_ai_review_plans(review_date DESC, id DESC)
        """
    )


def _migrate_default_api_config(conn: sqlite3.Connection, old_id_to_key: dict[int, str]) -> None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", ("default_api_config",)).fetchone()
    if not row:
        return
    try:
        config = json.loads(row["value"])
    except json.JSONDecodeError:
        return
    if not isinstance(config, dict) or config.get("provider_key"):
        return
    try:
        old_provider_id = int(config.get("provider_id", 0))
    except (TypeError, ValueError):
        old_provider_id = 0
    provider_key = old_id_to_key.get(old_provider_id)
    if not provider_key:
        return
    updated = {"provider_key": provider_key, "model": str(config.get("model") or "")}
    conn.execute(
        """
        UPDATE app_settings
        SET value = ?, updated_at = datetime('now', 'localtime')
        WHERE key = ?
        """,
        (json.dumps(updated, ensure_ascii=False), "default_api_config"),
    )


def _api_providers_schema_sql() -> str:
    return """
    CREATE TABLE api_providers (
        provider_key TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        provider_type TEXT NOT NULL,
        base_url TEXT DEFAULT '',
        model TEXT DEFAULT '',
        api_key_env TEXT DEFAULT '',
        auth_type TEXT NOT NULL DEFAULT 'bearer',
        extra_headers_json TEXT DEFAULT '{}',
        request_template_json TEXT DEFAULT '',
        response_path TEXT DEFAULT '',
        balance_query_enabled INTEGER NOT NULL DEFAULT 0,
        balance_query_type TEXT NOT NULL DEFAULT 'auto_wallet',
        balance_query_config_json TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
    """


def _daily_ai_review_plans_schema_sql() -> str:
    return """
    CREATE TABLE daily_ai_review_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 0,
        review_date TEXT NOT NULL,
        provider_key TEXT,
        model TEXT DEFAULT '',
        plan_json TEXT NOT NULL DEFAULT '{}',
        source_snapshot_json TEXT NOT NULL DEFAULT '{}',
        answers_json TEXT DEFAULT '{}',
        evaluation_json TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT '待回答',
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        evaluated_at TEXT DEFAULT '',
        UNIQUE(user_id, review_date),
        FOREIGN KEY (provider_key) REFERENCES api_providers(provider_key) ON DELETE SET NULL
    )
    """


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _unique_provider_key(name: str, used_keys: set[str]) -> str:
    return _dedupe_provider_key(_slugify_provider_key(name), used_keys)


def _dedupe_provider_key(base_key: str, used_keys: set[str]) -> str:
    base = base_key.strip("-") or "provider"
    candidate = base
    suffix = 2
    while candidate in used_keys:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_keys.add(candidate)
    return candidate


def _slugify_provider_key(value: str) -> str:
    chars: list[str] = []
    for char in value.strip().lower():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "-":
            chars.append("-")
    return "".join(chars).strip("-")[:80] or "provider"


def fetch_all(query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with managed_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def fetch_one(query: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    with managed_connection() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    return dict(row) if row else None


def execute(query: str, params: Iterable[Any] = ()) -> None:
    with managed_connection() as conn:
        conn.execute(query, tuple(params))


def execute_many(query: str, params_seq: Iterable[Iterable[Any]]) -> None:
    with managed_connection() as conn:
        conn.executemany(query, (tuple(params) for params in params_seq))


def insert_and_get_id(query: str, params: Iterable[Any] = ()) -> int:
    with managed_connection() as conn:
        cursor = conn.execute(query, tuple(params))
        return int(cursor.lastrowid)
