from __future__ import annotations

import inspect
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from pages import ppt_tutor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READER_HTML = PROJECT_ROOT / "components" / "synced_reader" / "index.html"


class PptLearningWorkflowV2RegressionTest(unittest.TestCase):
    def test_pending_deck_wins_over_remembered_position_on_page_entry(self):
        selected = ppt_tutor._reader_deck_id_for_render(
            [7, 24],
            {"deck_id": 7, "slide_number": 301},
            24,
            page_just_entered=True,
            pending_deck_id=24,
        )

        self.assertEqual(selected, 24)
        self.assertIn(
            "pending_deck_id=",
            inspect.getsource(ppt_tutor.render),
        )

    def test_pending_history_course_is_consumed_before_reader_widgets(self):
        state = {
            ppt_tutor.PPT_PENDING_LEARNING_TARGET_KEY: {
                "deck_id": 24,
                "course_id": 8,
                "slide_number": 31,
                "include_history": True,
            }
        }
        with patch.object(ppt_tutor.st, "session_state", state):
            target = ppt_tutor.consume_pending_learning_target()

        self.assertEqual(target["course_id"], 8)
        self.assertEqual(state[ppt_tutor.PPT_HISTORY_COURSE_STATE_KEY], 8)
        self.assertEqual(state[ppt_tutor.PPT_HISTORY_DECK_STATE_KEY], 24)

    def test_reader_query_allows_every_owned_deck_in_explicit_history_course(self):
        captured: dict[str, object] = {}

        def fake_fetch_all(query, params):
            captured["query"] = query
            captured["params"] = params
            return [{"id": 11}, {"id": 12}]

        with patch.object(ppt_tutor, "fetch_all", side_effect=fake_fetch_all):
            rows = ppt_tutor._fetch_reader_decks(
                42,
                history_deck_id=11,
                history_course_id=8,
            )

        normalized_sql = " ".join(str(captured["query"]).split())
        self.assertEqual([row["id"] for row in rows], [11, 12])
        self.assertIn("WHERE d.user_id = ?", normalized_sql)
        self.assertIn("OR d.id = ?", normalized_sql)
        self.assertIn("OR d.course_id = ?", normalized_sql)
        self.assertEqual(captured["params"], (42, 11, 8))

    def test_history_course_query_excludes_other_courses_and_other_users(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE courses (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE ppt_decks (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                course_id INTEGER,
                status TEXT,
                category TEXT,
                sort_order INTEGER,
                created_at TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO courses (id, user_id, status) VALUES (?, ?, ?)",
            [(1, 42, "active"), (8, 42, "archived"), (9, 42, "archived"), (10, 99, "archived")],
        )
        conn.executemany(
            """
            INSERT INTO ppt_decks (
                id, user_id, course_id, status, category, sort_order, created_at
            ) VALUES (?, ?, ?, '使用中', '', 0, '2026-08-23')
            """,
            [(7, 42, 1), (11, 42, 8), (12, 42, 8), (13, 42, 9), (99, 99, 10)],
        )

        def query_rows(query, params):
            return [dict(row) for row in conn.execute(query, params).fetchall()]

        try:
            with patch.object(ppt_tutor, "fetch_all", side_effect=query_rows):
                rows = ppt_tutor._fetch_reader_decks(
                    42,
                    history_deck_id=11,
                    history_course_id=8,
                )
        finally:
            conn.close()

        self.assertEqual({row["id"] for row in rows}, {7, 11, 12})

    def test_reader_query_only_uses_legacy_fallback_for_missing_course_schema(self):
        with patch.object(
            ppt_tutor,
            "fetch_all",
            side_effect=[
                sqlite3.OperationalError("near SELECT: syntax error"),
                [{"id": 99}],
            ],
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "syntax error"):
                ppt_tutor._fetch_reader_decks(42)

        with patch.object(
            ppt_tutor,
            "fetch_all",
            side_effect=[
                sqlite3.OperationalError("no such table: courses"),
                [{"id": 7}],
            ],
        ):
            self.assertEqual(ppt_tutor._fetch_reader_decks(42), [{"id": 7}])

    def test_learning_records_include_direct_and_session_page_cards_without_duplicates(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE ppt_slides (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                deck_id INTEGER NOT NULL,
                slide_number INTEGER NOT NULL
            );
            CREATE TABLE knowledge_cards (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                source_slide_id INTEGER,
                source_session_id INTEGER,
                source_question_id INTEGER,
                topic TEXT,
                mastery INTEGER,
                need_review INTEGER,
                created_at TEXT
            );
            CREATE TABLE ppt_study_asset_pages (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                deck_id INTEGER NOT NULL,
                slide_number INTEGER NOT NULL,
                session_id INTEGER
            );
            CREATE TABLE review_tasks (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                knowledge_id INTEGER NOT NULL,
                review_date TEXT,
                status TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO ppt_slides (id, user_id, deck_id, slide_number) VALUES (?, ?, ?, ?)",
            [(101, 42, 5, 3), (201, 99, 6, 3)],
        )
        conn.executemany(
            """
            INSERT INTO knowledge_cards (
                id, user_id, source_slide_id, source_session_id,
                source_question_id, topic, mastery, need_review, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 42, 101, None, 9001, "直接卡", 70, 1, "2026-08-20"),
                (2, 42, None, 55, None, "学习资产卡", 60, 1, "2026-08-21"),
                (3, 99, None, 55, None, "其他用户卡", 10, 1, "2026-08-22"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO ppt_study_asset_pages (id, user_id, deck_id, slide_number, session_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(1, 42, 5, 3, 55), (2, 42, 5, 3, 55), (3, 99, 6, 3, 55)],
        )
        conn.executemany(
            """
            INSERT INTO review_tasks (id, user_id, knowledge_id, review_date, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, 42, 1, "2026-09-01", "待复习"),
                (2, 42, 2, "2026-08-30", "待复习"),
                (3, 99, 3, "2026-08-29", "待复习"),
            ],
        )

        def query_rows(query, params):
            return [dict(row) for row in conn.execute(query, params).fetchall()]

        try:
            with patch.object(ppt_tutor, "fetch_all", side_effect=query_rows):
                records = ppt_tutor._learning_records_by_slide_ids(42, [101])
        finally:
            conn.close()

        cards = records[101]["knowledge_cards"]
        self.assertEqual({card["id"] for card in cards}, {1, 2})
        self.assertEqual(len(cards), 2)
        self.assertNotIn(3, {card["id"] for card in cards})
        self.assertEqual(records[101]["review_status"]["pending_count"], 2)
        self.assertEqual(
            records[101]["review_status"]["next_review_date"],
            "2026-08-30",
        )

    def test_question_tree_styles_distinguish_grandchildren_from_children(self):
        html = READER_HTML.read_text(encoding="utf-8")

        self.assertIn('data-parent-question-id=', html)
        self.assertIn('.chat-turn[data-depth="2"]', html)
        self.assertIn('.chat-turn[data-depth="3"]', html)
        self.assertIn("问题树", html)

    def test_local_upload_requires_a_nonempty_subject(self):
        with self.assertRaisesRegex(ValueError, "科目"):
            ppt_tutor._required_upload_subject("   ")

        self.assertEqual(ppt_tutor._required_upload_subject("  信号与系统  "), "信号与系统")
        self.assertIn(
            "_required_upload_subject(subject)",
            inspect.getsource(ppt_tutor._render_upload_form),
        )

    def test_study_asset_writer_is_available_only_for_active_owned_course(self):
        self.assertTrue(
            ppt_tutor._study_asset_learning_writable(
                {"course_id": 8, "course_status": "active"}
            )
        )
        for deck in (
            {"course_id": 8, "course_status": "completed"},
            {"course_id": 8, "course_status": "archived"},
            {"course_id": None, "course_status": ""},
        ):
            with self.subTest(deck=deck):
                self.assertFalse(ppt_tutor._study_asset_learning_writable(deck))

        source = inspect.getsource(ppt_tutor._render_study_asset_generator_inner)
        self.assertIn("_study_asset_learning_writable(deck)", source)
        self.assertIn('source_deck_id=int(deck["id"])', source)


if __name__ == "__main__":
    unittest.main()
