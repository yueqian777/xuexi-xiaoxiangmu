from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "study_manager.db"
SQLITE_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = SQLITE_TIMEOUT_SECONDS * 1000
WRITE_RETRY_ATTEMPTS = 4
_INIT_LOCK = threading.Lock()
_INITIALIZED_DATABASE_PATH: Path | None = None


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


@contextmanager
def managed_connection(*, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    global _INITIALIZED_DATABASE_PATH
    if _INITIALIZED_DATABASE_PATH == DATABASE_PATH and DATABASE_PATH.exists():
        return
    with _INIT_LOCK:
        if _INITIALIZED_DATABASE_PATH == DATABASE_PATH and DATABASE_PATH.exists():
            return
        _run_init_db()
        _INITIALIZED_DATABASE_PATH = DATABASE_PATH


def _run_init_db() -> None:
    with managed_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
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
                source_deck_id INTEGER,
                source_slide_id INTEGER,
                source_question_id INTEGER,
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
                outline TEXT DEFAULT '',
                outline_generated_at TEXT DEFAULT '',
                import_package_id INTEGER,
                source_type TEXT NOT NULL DEFAULT 'local_upload',
                source_package_id TEXT DEFAULT '',
                imported_at TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS import_packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                package_id TEXT NOT NULL,
                package_type TEXT NOT NULL,
                package_version TEXT NOT NULL DEFAULT '',
                privacy_mode TEXT NOT NULL DEFAULT '',
                subject TEXT DEFAULT '',
                title TEXT DEFAULT '',
                source_filename TEXT DEFAULT '',
                manifest_json TEXT NOT NULL DEFAULT '{}',
                imported_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
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
                section_index INTEGER NOT NULL DEFAULT 0,
                page_type TEXT DEFAULT '',
                one_sentence_summary TEXT DEFAULT '',
                slide_role TEXT DEFAULT '',
                key_points TEXT DEFAULT '',
                bookmark_enabled INTEGER NOT NULL DEFAULT 0,
                bookmark_title TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE,
                UNIQUE(deck_id, slide_number)
            );

            CREATE TABLE IF NOT EXISTS ppt_study_asset_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                deck_id INTEGER NOT NULL,
                slide_number INTEGER NOT NULL,
                session_id INTEGER,
                knowledge_count INTEGER NOT NULL DEFAULT 0,
                range_label TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES study_sessions(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS ppt_sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                deck_id INTEGER NOT NULL,
                section_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                topic TEXT DEFAULT '',
                core_question TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                key_terms_json TEXT NOT NULL DEFAULT '[]',
                prerequisite_concepts_json TEXT NOT NULL DEFAULT '[]',
                start_slide INTEGER NOT NULL,
                end_slide INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE,
                UNIQUE(deck_id, section_index)
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

            CREATE TABLE IF NOT EXISTS chatgpt_explanation_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                task_id TEXT NOT NULL,
                deck_id INTEGER NOT NULL,
                deck_fingerprint TEXT NOT NULL,
                requested_slides_json TEXT NOT NULL DEFAULT '[]',
                package_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'created',
                manifest_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                completed_at TEXT DEFAULT '',
                FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE,
                UNIQUE(user_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS chatgpt_explanation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                result_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                source_path TEXT NOT NULL DEFAULT '',
                slide_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'detected',
                raw_result_json TEXT NOT NULL DEFAULT '{}',
                imported_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(user_id, result_id),
                FOREIGN KEY (user_id, task_id)
                    REFERENCES chatgpt_explanation_tasks(user_id, task_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ppt_slide_animation_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                deck_id INTEGER NOT NULL,
                slide_id INTEGER NOT NULL,
                slide_number INTEGER NOT NULL,
                state_index INTEGER NOT NULL,
                label TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                step_summary TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (deck_id) REFERENCES ppt_decks(id) ON DELETE CASCADE,
                FOREIGN KEY (slide_id) REFERENCES ppt_slides(id) ON DELETE CASCADE,
                UNIQUE(user_id, slide_id, state_index)
            );

            CREATE TABLE IF NOT EXISTS slide_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                slide_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                quote_text TEXT DEFAULT '',
                answer TEXT NOT NULL,
                model TEXT NOT NULL,
                root_question_id INTEGER,
                parent_question_id INTEGER,
                depth INTEGER NOT NULL DEFAULT 0,
                quote_source TEXT DEFAULT 'slide',
                quote_source_question_id INTEGER,
                knowledge_id INTEGER,
                converted_to_knowledge INTEGER NOT NULL DEFAULT 0,
                understood INTEGER NOT NULL DEFAULT 0,
                need_review INTEGER NOT NULL DEFAULT 0,
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
                vision_capability TEXT NOT NULL DEFAULT 'auto',
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

            CREATE TABLE IF NOT EXISTS mcp_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                request_id TEXT NOT NULL CHECK(length(request_id) BETWEEN 1 AND 128),
                tool_name TEXT NOT NULL CHECK(length(tool_name) BETWEEN 1 AND 128),
                operation_type TEXT NOT NULL CHECK(operation_type IN ('READ', 'WRITE')),
                target_type TEXT NOT NULL DEFAULT '' CHECK(length(target_type) <= 64),
                target_id TEXT NOT NULL DEFAULT '' CHECK(length(target_id) <= 128),
                success INTEGER NOT NULL DEFAULT 0 CHECK(success IN (0, 1)),
                permission_result TEXT NOT NULL CHECK(permission_result IN ('allowed', 'permission_denied')),
                summary TEXT NOT NULL DEFAULT '' CHECK(length(summary) <= 300),
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS api_parallel_benchmarks (
                benchmark_key TEXT PRIMARY KEY,
                provider_key TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                api_key_fingerprint TEXT NOT NULL DEFAULT '',
                parallel_limit INTEGER NOT NULL DEFAULT 0,
                success_rate REAL NOT NULL DEFAULT 0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                rate_limit_count INTEGER NOT NULL DEFAULT 0,
                timeout_count INTEGER NOT NULL DEFAULT 0,
                probe_json TEXT NOT NULL DEFAULT '{}',
                is_authoritative INTEGER NOT NULL DEFAULT 0,
                invalidated_at TEXT DEFAULT '',
                invalidated_reason TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
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
        _ensure_column(conn, "knowledge_cards", "source_deck_id", "INTEGER")
        _ensure_column(conn, "knowledge_cards", "source_slide_id", "INTEGER")
        _ensure_column(conn, "knowledge_cards", "source_question_id", "INTEGER")
        _ensure_column(conn, "knowledge_links", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "mistakes", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "review_tasks", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "parking_lot", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "ppt_decks", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "ppt_decks", "outline", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_decks", "outline_generated_at", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_decks", "import_package_id", "INTEGER")
        _ensure_column(conn, "ppt_decks", "source_type", "TEXT NOT NULL DEFAULT 'local_upload'")
        _ensure_column(conn, "ppt_decks", "source_package_id", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_decks", "imported_at", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_slides", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "ppt_slides", "section_index", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "ppt_slides", "page_type", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_slides", "one_sentence_summary", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_slides", "slide_role", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_slides", "key_points", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_slides", "bookmark_enabled", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "ppt_slides", "bookmark_title", "TEXT DEFAULT ''")
        _ensure_column(conn, "ppt_study_asset_pages", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "ppt_sections", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "slide_explanations", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "chatgpt_explanation_tasks", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "chatgpt_explanation_tasks", "manifest_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "chatgpt_explanation_tasks", "completed_at", "TEXT DEFAULT ''")
        _ensure_column(conn, "chatgpt_explanation_results", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "chatgpt_explanation_results", "source_path", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "chatgpt_explanation_results", "slide_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "chatgpt_explanation_results", "status", "TEXT NOT NULL DEFAULT 'detected'")
        _ensure_column(conn, "chatgpt_explanation_results", "raw_result_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(
            conn,
            "chatgpt_explanation_results",
            "imported_at",
            "TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(conn, "slide_questions", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "slide_questions", "quote_text", "TEXT DEFAULT ''")
        _ensure_column(conn, "slide_questions", "root_question_id", "INTEGER")
        _ensure_column(conn, "slide_questions", "parent_question_id", "INTEGER")
        _ensure_column(conn, "slide_questions", "depth", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "slide_questions", "quote_source", "TEXT DEFAULT 'slide'")
        _ensure_column(conn, "slide_questions", "quote_source_question_id", "INTEGER")
        _ensure_column(conn, "slide_questions", "knowledge_id", "INTEGER")
        _ensure_column(conn, "slide_questions", "converted_to_knowledge", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "slide_questions", "understood", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "slide_questions", "need_review", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "api_providers", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "api_providers", "vision_capability", "TEXT NOT NULL DEFAULT 'auto'")
        _ensure_column(conn, "app_settings", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "daily_review_logs", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "daily_ai_review_plans", "user_id", "INTEGER NOT NULL DEFAULT 0")
        _migrate_course_schema(conn)
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_courses_user_status_updated
                ON courses(user_id, status, updated_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_courses_user_name
                ON courses(user_id, name, id ASC);
            CREATE INDEX IF NOT EXISTS idx_course_learning_phases_user_course
                ON course_learning_phases(user_id, course_id, phase_number ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_course_summaries_user_course_updated
                ON course_summaries(user_id, course_id, updated_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_study_sessions_user_course_date
                ON study_sessions(user_id, course_id, date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_user_course_mastery
                ON knowledge_cards(user_id, course_id, mastery ASC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_ppt_decks_user_course_created
                ON ppt_decks(user_id, course_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_study_sessions_user_date_id
                ON study_sessions(user_id, date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_study_sessions_user_subject_date_id
                ON study_sessions(user_id, subject, date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mainline_anchors_user_session_order
                ON mainline_anchors(user_id, session_id, order_index ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_mainline_anchors_session
                ON mainline_anchors(session_id);
            CREATE INDEX IF NOT EXISTS idx_branch_questions_user_anchor_created
                ON branch_questions(user_id, anchor_id, created_at ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_branch_questions_user_session_anchor
                ON branch_questions(user_id, session_id, anchor_id);
            CREATE INDEX IF NOT EXISTS idx_branch_questions_session
                ON branch_questions(session_id);
            CREATE INDEX IF NOT EXISTS idx_branch_questions_anchor
                ON branch_questions(anchor_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_user_mastery_created
                ON knowledge_cards(user_id, mastery ASC, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_user_subject_created
                ON knowledge_cards(user_id, subject, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_user_created
                ON knowledge_cards(user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_user_source_session
                ON knowledge_cards(user_id, source_session_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_cards_source_session
                ON knowledge_cards(source_session_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_cards_user_source_question_unique
                ON knowledge_cards(user_id, source_question_id)
                WHERE source_question_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_knowledge_links_user_source_created
                ON knowledge_links(user_id, source_knowledge_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_links_user_target_created
                ON knowledge_links(user_id, target_knowledge_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_links_source
                ON knowledge_links(source_knowledge_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_links_target
                ON knowledge_links(target_knowledge_id);
            CREATE INDEX IF NOT EXISTS idx_mistakes_user_knowledge_created
                ON mistakes(user_id, knowledge_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mistakes_knowledge
                ON mistakes(knowledge_id);
            CREATE INDEX IF NOT EXISTS idx_mistakes_user_subject_topic_created
                ON mistakes(user_id, subject, topic, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mistakes_user_created
                ON mistakes(user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mistakes_user_subject_cause
                ON mistakes(user_id, subject, cause_category);
            CREATE INDEX IF NOT EXISTS idx_review_tasks_user_status_date_id
                ON review_tasks(user_id, status, review_date ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_review_tasks_user_knowledge_date
                ON review_tasks(user_id, knowledge_id, review_date ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_review_tasks_knowledge_status_date
                ON review_tasks(knowledge_id, status, review_date ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_parking_lot_user_status_created
                ON parking_lot(user_id, status, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_parking_lot_user_created
                ON parking_lot(user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_ppt_decks_user_created
                ON ppt_decks(user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_ppt_decks_user_import_package
                ON ppt_decks(user_id, import_package_id);
            CREATE INDEX IF NOT EXISTS idx_import_packages_user_package
                ON import_packages(user_id, package_id);
            CREATE INDEX IF NOT EXISTS idx_ppt_slides_user_deck_number
                ON ppt_slides(user_id, deck_id, slide_number ASC);
            CREATE INDEX IF NOT EXISTS idx_ppt_slides_user_deck_bookmark
                ON ppt_slides(user_id, deck_id, bookmark_enabled, slide_number ASC);
            CREATE INDEX IF NOT EXISTS idx_ppt_slides_deck
                ON ppt_slides(deck_id);
            CREATE INDEX IF NOT EXISTS idx_ppt_study_asset_pages_user_deck_slide
                ON ppt_study_asset_pages(user_id, deck_id, slide_number ASC, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ppt_sections_user_deck_index
                ON ppt_sections(user_id, deck_id, section_index ASC);
            CREATE INDEX IF NOT EXISTS idx_ppt_sections_deck
                ON ppt_sections(deck_id);
            CREATE INDEX IF NOT EXISTS idx_slide_explanations_user_slide_created
                ON slide_explanations(user_id, slide_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_slide_explanations_slide
                ON slide_explanations(slide_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chatgpt_explanation_tasks_user_task
                ON chatgpt_explanation_tasks(user_id, task_id);
            CREATE INDEX IF NOT EXISTS idx_chatgpt_explanation_tasks_user_status_created
                ON chatgpt_explanation_tasks(user_id, status, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_chatgpt_explanation_tasks_user_deck_created
                ON chatgpt_explanation_tasks(user_id, deck_id, created_at DESC, id DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chatgpt_explanation_results_user_result
                ON chatgpt_explanation_results(user_id, result_id);
            CREATE INDEX IF NOT EXISTS idx_chatgpt_explanation_results_user_task_imported
                ON chatgpt_explanation_results(user_id, task_id, imported_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_chatgpt_explanation_results_user_status_imported
                ON chatgpt_explanation_results(user_id, status, imported_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mcp_audit_logs_user_created
                ON mcp_audit_logs(user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mcp_audit_logs_user_request
                ON mcp_audit_logs(user_id, request_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ppt_slide_animation_states_user_slide_index
                ON ppt_slide_animation_states(user_id, slide_id, state_index);
            CREATE INDEX IF NOT EXISTS idx_ppt_slide_animation_states_user_deck_slide
                ON ppt_slide_animation_states(user_id, deck_id, slide_number ASC, state_index ASC);
            CREATE INDEX IF NOT EXISTS idx_ppt_slide_animation_states_slide
                ON ppt_slide_animation_states(slide_id, state_index ASC);
            CREATE INDEX IF NOT EXISTS idx_slide_questions_user_slide_created
                ON slide_questions(user_id, slide_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_slide_questions_user_slide_parent_order
                ON slide_questions(user_id, slide_id, parent_question_id, sort_order ASC, created_at ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_slide_questions_user_root_order
                ON slide_questions(user_id, root_question_id, parent_question_id, sort_order ASC, created_at ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_slide_questions_user_parent_order
                ON slide_questions(user_id, parent_question_id, sort_order ASC, created_at ASC, id ASC);
            CREATE INDEX IF NOT EXISTS idx_slide_questions_slide
                ON slide_questions(slide_id);
            CREATE INDEX IF NOT EXISTS idx_slide_questions_user_knowledge
                ON slide_questions(user_id, knowledge_id);
            CREATE INDEX IF NOT EXISTS idx_daily_ai_review_plans_user_date
                ON daily_ai_review_plans(user_id, review_date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_api_parallel_benchmarks_provider
                ON api_parallel_benchmarks(provider_key, model, base_url, api_key_fingerprint);
            """
        )
        _migrate_api_provider_identity(conn)
        _migrate_daily_ai_review_plan_user_scope(conn)
        _migrate_ppt_study_asset_pages_user_scope(conn)
        _migrate_ppt_sections_user_scope(conn)
        _migrate_slide_question_trees(conn)
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


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_course_schema(conn: sqlite3.Connection) -> None:
    """Create and gently extend the course lifecycle schema.

    Existing subject-based rows are associated with an owned course when their
    link is empty, dangling, or cross-user. Knowledge-card provenance takes
    precedence over its display subject. In particular, this migration never
    changes ``ppt_decks.status`` because that column describes deck management,
    not the course lifecycle.
    """

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'completed', 'archived')),
            completed_at TEXT,
            archived_at TEXT,
            course_summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS course_learning_phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            course_id INTEGER NOT NULL,
            phase_number INTEGER NOT NULL DEFAULT 1,
            started_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            ended_at TEXT,
            outcome TEXT NOT NULL DEFAULT '',
            course_summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS course_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            course_id INTEGER NOT NULL,
            deck_count INTEGER NOT NULL DEFAULT 0,
            slide_count INTEGER NOT NULL DEFAULT 0,
            question_count INTEGER NOT NULL DEFAULT 0,
            knowledge_count INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            completed_review_count INTEGER NOT NULL DEFAULT 0,
            pending_review_count INTEGER NOT NULL DEFAULT 0,
            weak_points_json TEXT NOT NULL DEFAULT '[]',
            core_knowledge_json TEXT NOT NULL DEFAULT '[]',
            future_review_advice TEXT NOT NULL DEFAULT '',
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        );
        """
    )
    # Keep name normalization, duplicate reconciliation, content backfill, and
    # the active-course uniqueness guard in one writer transaction.  The
    # preceding executescript commits any pending transaction by design, so the
    # explicit BEGIN must live after it.
    conn.execute("BEGIN IMMEDIATE")
    # Older versions of this migration used an ASCII-TRIM expression index.
    # Drop it before Python's Unicode-aware normalization so a formerly
    # distinct name such as ``\u3000课程\u3000`` can be reconciled safely.
    conn.execute("DROP INDEX IF EXISTS idx_courses_user_active_name_unique")

    course_columns = _table_columns(conn, "courses")
    _ensure_column(conn, "courses", "user_id", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "courses", "name", "TEXT DEFAULT ''")
    _ensure_column(conn, "courses", "status", "TEXT DEFAULT 'active'")
    _ensure_column(conn, "courses", "completed_at", "TEXT")
    _ensure_column(conn, "courses", "archived_at", "TEXT")
    _ensure_column(conn, "courses", "course_summary", "TEXT DEFAULT ''")
    _ensure_column(conn, "courses", "created_at", "TEXT DEFAULT ''")
    _ensure_column(conn, "courses", "updated_at", "TEXT DEFAULT ''")
    conn.execute("UPDATE courses SET user_id = 0 WHERE user_id IS NULL")

    for legacy_name_column in ("subject", "course_name", "title"):
        if legacy_name_column in course_columns:
            conn.execute(
                f"""
                UPDATE courses
                SET name = TRIM(COALESCE({legacy_name_column}, ''))
                WHERE TRIM(COALESCE(name, '')) = ''
                  AND TRIM(COALESCE({legacy_name_column}, '')) != ''
                """
            )
            break
    conn.execute(
        """
        UPDATE courses
        SET name = '未命名课程 ' || id
        WHERE TRIM(COALESCE(name, '')) = ''
        """
    )
    python_legacy_name_columns = [
        column
        for column in ("subject", "course_name", "title")
        if column in course_columns
    ]
    course_name_select = ", ".join(["id", "name", *python_legacy_name_columns])
    for course_row in conn.execute(
        f"SELECT {course_name_select} FROM courses"
    ).fetchall():
        candidates = [course_row["name"]]
        candidates.extend(course_row[column] for column in python_legacy_name_columns)
        normalized_name = next(
            (str(candidate or "").strip() for candidate in candidates if str(candidate or "").strip()),
            f"未命名课程 {int(course_row['id'])}",
        )
        if normalized_name != course_row["name"]:
            conn.execute(
                "UPDATE courses SET name = ? WHERE id = ?",
                (normalized_name, int(course_row["id"])),
            )
    conn.execute(
        """
        UPDATE courses
        SET status = CASE TRIM(COALESCE(status, ''))
            WHEN 'completed' THEN 'completed'
            WHEN 'archived' THEN 'archived'
            WHEN '已完成' THEN 'completed'
            WHEN '已归档' THEN 'archived'
            ELSE 'active'
        END
        """
    )
    conn.execute(
        """
        UPDATE courses
        SET created_at = datetime('now', 'localtime')
        WHERE TRIM(COALESCE(created_at, '')) = ''
        """
    )
    conn.execute(
        """
        UPDATE courses
        SET updated_at = COALESCE(NULLIF(created_at, ''), datetime('now', 'localtime'))
        WHERE TRIM(COALESCE(updated_at, '')) = ''
        """
    )
    _ensure_column(conn, "course_learning_phases", "user_id", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "course_learning_phases", "course_id", "INTEGER")
    _ensure_column(conn, "course_learning_phases", "phase_number", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "course_learning_phases", "started_at", "TEXT DEFAULT ''")
    _ensure_column(conn, "course_learning_phases", "ended_at", "TEXT")
    _ensure_column(conn, "course_learning_phases", "outcome", "TEXT DEFAULT ''")
    _ensure_column(conn, "course_learning_phases", "course_summary", "TEXT DEFAULT ''")
    _ensure_column(conn, "course_learning_phases", "created_at", "TEXT DEFAULT ''")
    _backfill_course_terminal_timestamps(conn)

    summary_columns = _table_columns(conn, "course_summaries")
    _ensure_column(conn, "course_summaries", "user_id", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "course_summaries", "course_id", "INTEGER")
    _ensure_column(conn, "course_summaries", "deck_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "course_summaries", "slide_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "course_summaries", "question_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "course_summaries", "knowledge_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "course_summaries", "review_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(
        conn,
        "course_summaries",
        "completed_review_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(
        conn,
        "course_summaries",
        "pending_review_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(conn, "course_summaries", "weak_points_json", "TEXT DEFAULT '[]'")
    _ensure_column(conn, "course_summaries", "core_knowledge_json", "TEXT DEFAULT '[]'")
    _ensure_column(conn, "course_summaries", "future_review_advice", "TEXT DEFAULT ''")
    _ensure_column(conn, "course_summaries", "summary_json", "TEXT DEFAULT '{}'")
    _ensure_column(conn, "course_summaries", "created_at", "TEXT DEFAULT ''")
    _ensure_column(conn, "course_summaries", "updated_at", "TEXT DEFAULT ''")

    legacy_summary_columns = {
        "review_total": "review_count",
        "review_completed": "completed_review_count",
        "review_pending": "pending_review_count",
        "future_review_suggestion": "future_review_advice",
        "weak_knowledge_json": "weak_points_json",
    }
    for old_column, new_column in legacy_summary_columns.items():
        if old_column not in summary_columns:
            continue
        conn.execute(
            f"""
            UPDATE course_summaries
            SET {new_column} = {old_column}
            WHERE ({new_column} IS NULL OR {new_column} IN ('', 0, '[]', '{{}}'))
              AND {old_column} IS NOT NULL
            """
        )

    _ensure_column(conn, "ppt_decks", "course_id", "INTEGER")
    _ensure_column(conn, "study_sessions", "course_id", "INTEGER")
    _ensure_column(conn, "knowledge_cards", "course_id", "INTEGER")

    _repair_invalid_course_asset_links(conn)
    _backfill_course_child_user_scope(conn)
    _normalize_duplicate_active_courses(conn)
    _backfill_subject_courses(conn)
    _ensure_initial_course_phases(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_user_active_name_unique
        ON courses(user_id, TRIM(name))
        WHERE status = 'active'
        """
    )


def _backfill_course_terminal_timestamps(conn: sqlite3.Connection) -> None:
    for status, localized_status, timestamp_column in (
        ("completed", "已完成", "completed_at"),
        ("archived", "已归档", "archived_at"),
    ):
        extra_fallback = (
            "NULLIF(TRIM(course.completed_at), ''),"
            if status == "archived"
            else ""
        )
        conn.execute(
            f"""
            UPDATE courses AS course
            SET {timestamp_column} = COALESCE(
                NULLIF(TRIM({timestamp_column}), ''),
                (
                    SELECT MAX(NULLIF(TRIM(phase.ended_at), ''))
                    FROM course_learning_phases AS phase
                    WHERE phase.course_id = course.id
                      AND TRIM(COALESCE(phase.outcome, '')) IN (?, ?)
                ),
                NULLIF(TRIM(course.updated_at), ''),
                {extra_fallback}
                NULLIF(TRIM(course.created_at), ''),
                datetime('now', 'localtime')
            )
            WHERE course.status = ?
              AND TRIM(COALESCE(course.{timestamp_column}, '')) = ''
            """,
            (status, localized_status, status),
        )


def _backfill_subject_courses(conn: sqlite3.Connection) -> None:
    _backfill_subject_rows(conn, ("ppt_decks", "study_sessions"))
    _backfill_knowledge_card_courses_from_sources(conn)
    _backfill_subject_rows(conn, ("knowledge_cards",))


def _backfill_subject_rows(
    conn: sqlite3.Connection,
    tables: tuple[str, ...],
) -> None:
    allowed_tables = {"ppt_decks", "study_sessions", "knowledge_cards"}
    if not tables or any(table not in allowed_tables for table in tables):
        raise ValueError("Unsupported course backfill table.")
    course_cache: dict[tuple[int, str], int] = {}
    for table in tables:
        assets = conn.execute(
            f"""
            SELECT id, user_id, subject
            FROM {table}
            WHERE course_id IS NULL OR course_id <= 0
            ORDER BY user_id ASC, id ASC
            """
        ).fetchall()
        for asset in assets:
            user_id = int(asset["user_id"] or 0)
            name = str(asset["subject"] or "").strip()
            if not name:
                continue
            cache_key = (user_id, name)
            course_id = course_cache.get(cache_key)
            if course_id is None:
                course = conn.execute(
                    """
                    SELECT id
                    FROM courses
                    WHERE user_id = ? AND name = ?
                    ORDER BY CASE status
                                 WHEN 'active' THEN 0
                                 WHEN 'completed' THEN 1
                                 ELSE 2
                             END,
                             COALESCE(updated_at, '') DESC,
                             id DESC
                    LIMIT 1
                    """,
                    (user_id, name),
                ).fetchone()
                if course:
                    course_id = int(course["id"])
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO courses (user_id, name, status)
                        VALUES (?, ?, 'active')
                        """,
                        (user_id, name),
                    )
                    course_id = int(cursor.lastrowid)
                course_cache[cache_key] = course_id
            conn.execute(
                f"""
                UPDATE {table}
                SET course_id = ?
                WHERE id = ? AND user_id = ?
                  AND (course_id IS NULL OR course_id <= 0)
                """,
                (course_id, int(asset["id"]), user_id),
            )


def _repair_invalid_course_asset_links(conn: sqlite3.Connection) -> None:
    for table in ("ppt_decks", "study_sessions", "knowledge_cards"):
        conn.execute(
            f"""
            UPDATE {table} AS asset
            SET course_id = NULL
            WHERE course_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM courses AS course
                  WHERE course.id = asset.course_id
                    AND course.user_id = asset.user_id
              )
            """
        )


def _backfill_knowledge_card_courses_from_sources(conn: sqlite3.Connection) -> None:
    canonical_course = """
        COALESCE(
            (
                SELECT course.id
                FROM ppt_decks AS deck
                JOIN courses AS course
                  ON course.id = deck.course_id
                 AND course.user_id = deck.user_id
                WHERE deck.id = card.source_deck_id
                  AND deck.user_id = card.user_id
                LIMIT 1
            ),
            (
                SELECT course.id
                FROM ppt_slides AS slide
                JOIN ppt_decks AS deck
                  ON deck.id = slide.deck_id
                 AND deck.user_id = slide.user_id
                JOIN courses AS course
                  ON course.id = deck.course_id
                 AND course.user_id = deck.user_id
                WHERE slide.id = card.source_slide_id
                  AND slide.user_id = card.user_id
                LIMIT 1
            ),
            (
                SELECT course.id
                FROM slide_questions AS question
                JOIN ppt_slides AS slide
                  ON slide.id = question.slide_id
                 AND slide.user_id = question.user_id
                JOIN ppt_decks AS deck
                  ON deck.id = slide.deck_id
                 AND deck.user_id = slide.user_id
                JOIN courses AS course
                  ON course.id = deck.course_id
                 AND course.user_id = deck.user_id
                WHERE question.id = card.source_question_id
                  AND question.user_id = card.user_id
                LIMIT 1
            ),
            (
                SELECT course.id
                FROM study_sessions AS session
                JOIN courses AS course
                  ON course.id = session.course_id
                 AND course.user_id = session.user_id
                WHERE session.id = card.source_session_id
                  AND session.user_id = card.user_id
                LIMIT 1
            )
        )
    """
    conn.execute(
        f"""
        UPDATE knowledge_cards AS card
        SET course_id = {canonical_course}
        WHERE {canonical_course} IS NOT NULL
          AND course_id IS NOT {canonical_course}
        """
    )


def _normalize_duplicate_active_courses(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, user_id, TRIM(name) AS normalized_name, updated_at
        FROM courses
        WHERE status = 'active'
        ORDER BY user_id ASC, TRIM(name) ASC,
                 COALESCE(updated_at, '') DESC, id DESC
        """
    ).fetchall()
    seen: set[tuple[int, str]] = set()
    for row in rows:
        key = (int(row["user_id"] or 0), str(row["normalized_name"] or ""))
        if key not in seen:
            seen.add(key)
            continue
        course_id = int(row["id"])
        terminal_at = str(row["updated_at"] or "").strip()
        conn.execute(
            """
            UPDATE courses
            SET status = 'archived',
                archived_at = COALESCE(
                    NULLIF(TRIM(archived_at), ''),
                    NULLIF(?, ''),
                    datetime('now', 'localtime')
                ),
                updated_at = datetime('now', 'localtime')
            WHERE id = ? AND user_id = ? AND status = 'active'
            """,
            (terminal_at, course_id, key[0]),
        )
        conn.execute(
            """
            UPDATE course_learning_phases
            SET ended_at = COALESCE(
                    NULLIF(TRIM(ended_at), ''),
                    NULLIF(?, ''),
                    datetime('now', 'localtime')
                ),
                outcome = 'archived'
            WHERE course_id = ? AND user_id = ?
              AND TRIM(COALESCE(ended_at, '')) = ''
            """,
            (terminal_at, course_id, key[0]),
        )


def _backfill_course_child_user_scope(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE course_learning_phases AS phase
        SET user_id = (
            SELECT course.user_id
            FROM courses AS course
            WHERE course.id = phase.course_id
        )
        WHERE EXISTS (
            SELECT 1 FROM courses AS course WHERE course.id = phase.course_id
        )
          AND phase.user_id IS NOT (
              SELECT course.user_id
              FROM courses AS course
              WHERE course.id = phase.course_id
          )
        """
    )
    conn.execute(
        """
        UPDATE course_summaries AS summary
        SET user_id = (
            SELECT course.user_id
            FROM courses AS course
            WHERE course.id = summary.course_id
        )
        WHERE EXISTS (
            SELECT 1 FROM courses AS course WHERE course.id = summary.course_id
        )
          AND summary.user_id IS NOT (
              SELECT course.user_id
              FROM courses AS course
              WHERE course.id = summary.course_id
          )
        """
    )


def _ensure_initial_course_phases(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO course_learning_phases (
            user_id, course_id, phase_number, started_at, ended_at, outcome, created_at
        )
        SELECT
            c.user_id,
            c.id,
            1,
            COALESCE(NULLIF(c.created_at, ''), datetime('now', 'localtime')),
            CASE
                WHEN c.status = 'active' THEN NULL
                WHEN c.status = 'archived' THEN COALESCE(c.archived_at, c.completed_at, datetime('now', 'localtime'))
                ELSE COALESCE(c.completed_at, c.archived_at, datetime('now', 'localtime'))
            END,
            CASE WHEN c.status = 'active' THEN '' ELSE c.status END,
            COALESCE(NULLIF(c.created_at, ''), datetime('now', 'localtime'))
        FROM courses c
        WHERE NOT EXISTS (
            SELECT 1
            FROM course_learning_phases p
            WHERE p.user_id = c.user_id AND p.course_id = c.id
        )
        """
    )


def _migrate_ppt_sections_user_scope(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE ppt_sections
        SET user_id = COALESCE(
            (SELECT d.user_id FROM ppt_decks d WHERE d.id = ppt_sections.deck_id),
            NULLIF(user_id, 0),
            0
        )
        WHERE COALESCE(user_id, 0) = 0
        """
    )


def _migrate_ppt_study_asset_pages_user_scope(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE ppt_study_asset_pages
        SET user_id = COALESCE(
            (SELECT d.user_id FROM ppt_decks d WHERE d.id = ppt_study_asset_pages.deck_id),
            NULLIF(user_id, 0),
            0
        )
        WHERE COALESCE(user_id, 0) = 0
        """
    )


def _migrate_slide_question_trees(conn: sqlite3.Connection) -> None:
    scopes = conn.execute(
        """
        SELECT DISTINCT user_id, slide_id
        FROM slide_questions
        ORDER BY user_id ASC, slide_id ASC
        """
    ).fetchall()
    for scope in scopes:
        normalize_slide_question_tree_for_scope(conn, int(scope["user_id"] or 0), int(scope["slide_id"]))


def normalize_slide_question_tree_for_scope(conn: sqlite3.Connection, user_id: int, slide_id: int) -> int:
    rows = conn.execute(
        """
        SELECT id, parent_question_id, root_question_id, depth, sort_order, created_at
        FROM slide_questions
        WHERE user_id = ? AND slide_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (int(user_id), int(slide_id)),
    ).fetchall()
    if not rows:
        return 0

    nodes = {int(row["id"]): dict(row) for row in rows}
    children_by_parent: dict[int, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for node in nodes.values():
        parent_id = node.get("parent_question_id")
        parent_id = int(parent_id) if parent_id is not None else None
        if parent_id is not None and parent_id in nodes:
            children_by_parent.setdefault(parent_id, []).append(node)
        else:
            roots.append(node)

    def sibling_key(node: dict[str, Any]) -> tuple[int, int, str, int]:
        sort_order = int(node.get("sort_order") or 0)
        return (
            0 if sort_order > 0 else 1,
            sort_order if sort_order > 0 else 0,
            str(node.get("created_at") or ""),
            int(node["id"]),
        )

    updates: list[tuple[int, int, int, int, int, int]] = []
    visited: set[int] = set()

    def visit(node: dict[str, Any], *, root_id: int, depth: int, sort_order: int) -> None:
        node_id = int(node["id"])
        if node_id in visited:
            return
        visited.add(node_id)
        updates.append((root_id, depth, sort_order, int(user_id), int(slide_id), node_id))
        children = sorted(children_by_parent.get(node_id, []), key=sibling_key)
        for index, child in enumerate(children, start=1):
            visit(child, root_id=root_id, depth=depth + 1, sort_order=index)

    for index, root in enumerate(sorted(roots, key=sibling_key), start=1):
        visit(root, root_id=int(root["id"]), depth=0, sort_order=index)

    # Cycles should not exist, but legacy/manual edits can create them. Keep every row reachable.
    remaining = [node for node_id, node in nodes.items() if node_id not in visited]
    for index, root in enumerate(sorted(remaining, key=sibling_key), start=1):
        visit(root, root_id=int(root["id"]), depth=0, sort_order=index)

    conn.executemany(
        """
        UPDATE slide_questions
        SET root_question_id = ?, depth = ?, sort_order = ?
        WHERE user_id = ? AND slide_id = ? AND id = ?
        """,
        updates,
    )
    return len(updates)


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
            provider_key, user_id, name, provider_type, base_url, model, api_key_env,
            auth_type, extra_headers_json, request_template_json, response_path,
            balance_query_enabled, balance_query_type, balance_query_config_json,
            enabled, sort_order, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                item["provider_key"],
                int(item.get("user_id") or 0),
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
    has_user_id = "user_id" in columns
    rows = conn.execute("SELECT * FROM daily_ai_review_plans ORDER BY id ASC").fetchall()
    conn.execute("DROP INDEX IF EXISTS idx_daily_ai_review_plans_date")
    conn.execute("ALTER TABLE daily_ai_review_plans RENAME TO daily_ai_review_plans_old_provider_identity")
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
                int(row["user_id"] or 0) if has_user_id else 0,
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
        vision_capability TEXT NOT NULL DEFAULT 'auto',
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


@contextmanager
def write_transaction(*, attempts: int = WRITE_RETRY_ATTEMPTS) -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    delay = 0.05
    try:
        for attempt in range(max(1, attempts)):
            try:
                conn.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                if attempt == attempts - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
