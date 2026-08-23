from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

import db


class CourseMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()

    def test_legacy_subject_rows_are_backfilled_per_user_without_data_loss(self) -> None:
        deck_ids: list[int] = []
        session_ids: list[int] = []
        card_ids: list[int] = []
        question_ids: list[int] = []
        for user_id in (11, 22):
            deck_id = db.insert_and_get_id(
                """
                INSERT INTO ppt_decks (
                    user_id, filename, title, subject, status, file_path, slide_count, course_id
                )
                VALUES (?, ?, ?, '信号与系统', '仿真中', ?, 1, NULL)
                """,
                (user_id, f"signals-{user_id}.pdf", f"用户 {user_id} 课件", f"signals-{user_id}.pdf"),
            )
            slide_id = db.insert_and_get_id(
                """
                INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text)
                VALUES (?, ?, 1, '卷积', '旧课件正文')
                """,
                (user_id, deck_id),
            )
            question_id = db.insert_and_get_id(
                """
                INSERT INTO slide_questions (user_id, slide_id, question, answer, model)
                VALUES (?, ?, '卷积为什么成立？', '旧插问回答', 'legacy-model')
                """,
                (user_id, slide_id),
            )
            session_id = db.insert_and_get_id(
                """
                INSERT INTO study_sessions (
                    user_id, date, subject, title, main_question, course_id
                )
                VALUES (?, '2026-01-02', '信号与系统', '旧学习记录', '系统如何响应？', NULL)
                """,
                (user_id,),
            )
            card_id = db.insert_and_get_id(
                """
                INSERT INTO knowledge_cards (
                    user_id, subject, topic, one_sentence, source_session_id, course_id
                )
                VALUES (?, '信号与系统', '卷积', '卷积描述系统响应', ?, NULL)
                """,
                (user_id, session_id),
            )
            deck_ids.append(deck_id)
            session_ids.append(session_id)
            card_ids.append(card_id)
            question_ids.append(question_id)

        # Reproduce the state of an older database: subject text exists, but no
        # lifecycle rows are available to bind those assets yet.
        db.execute("DELETE FROM course_learning_phases")
        db.execute("DELETE FROM course_summaries")
        db.execute("DELETE FROM courses")

        for _ in range(2):
            db._INITIALIZED_DATABASE_PATH = None
            db.init_db()

        courses = db.fetch_all(
            "SELECT id, user_id, name, status FROM courses ORDER BY user_id, id"
        )
        self.assertEqual(
            [(row["user_id"], row["name"], row["status"]) for row in courses],
            [(11, "信号与系统", "active"), (22, "信号与系统", "active")],
        )
        course_by_user = {row["user_id"]: row["id"] for row in courses}

        for index, user_id in enumerate((11, 22)):
            deck = db.fetch_one(
                "SELECT course_id, status, title FROM ppt_decks WHERE id = ? AND user_id = ?",
                (deck_ids[index], user_id),
            )
            session = db.fetch_one(
                "SELECT course_id, title FROM study_sessions WHERE id = ? AND user_id = ?",
                (session_ids[index], user_id),
            )
            card = db.fetch_one(
                "SELECT course_id, topic FROM knowledge_cards WHERE id = ? AND user_id = ?",
                (card_ids[index], user_id),
            )
            question = db.fetch_one(
                "SELECT question, answer FROM slide_questions WHERE id = ? AND user_id = ?",
                (question_ids[index], user_id),
            )
            expected_course_id = course_by_user[user_id]
            self.assertEqual(deck, {"course_id": expected_course_id, "status": "仿真中", "title": f"用户 {user_id} 课件"})
            self.assertEqual(session, {"course_id": expected_course_id, "title": "旧学习记录"})
            self.assertEqual(card, {"course_id": expected_course_id, "topic": "卷积"})
            self.assertEqual(question, {"question": "卷积为什么成立？", "answer": "旧插问回答"})

        phases = db.fetch_all(
            "SELECT user_id, course_id, COUNT(*) AS count FROM course_learning_phases GROUP BY user_id, course_id"
        )
        self.assertEqual(
            {(row["user_id"], row["course_id"], row["count"]) for row in phases},
            {(11, course_by_user[11], 1), (22, course_by_user[22], 1)},
        )

    def test_unbound_assets_prefer_same_named_active_course_over_history(self) -> None:
        archived_id = db.insert_and_get_id(
            "INSERT INTO courses (user_id, name, status) VALUES (31, '自动控制', 'archived')"
        )
        active_id = db.insert_and_get_id(
            "INSERT INTO courses (user_id, name, status) VALUES (31, '自动控制', 'active')"
        )
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, filename, title, subject, file_path, course_id
            )
            VALUES (31, 'control.pdf', '控制系统', '自动控制', 'control.pdf', NULL)
            """
        )

        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()

        deck = db.fetch_one("SELECT course_id FROM ppt_decks WHERE id = ?", (deck_id,))
        self.assertEqual(deck["course_id"], active_id)
        self.assertNotEqual(deck["course_id"], archived_id)


class LegacyCourseSchemaMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None

    def test_nullable_owner_and_spaced_status_are_normalized_before_phase_backfill(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    title TEXT,
                    status TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO courses (user_id, title, status) VALUES (NULL, '旧课程', ' active ')"
            )
            conn.execute(
                "INSERT INTO courses (user_id, title, status) VALUES (7, '旧完成课', ' 已完成 ')"
            )

        for _ in range(2):
            db._INITIALIZED_DATABASE_PATH = None
            db.init_db()

        courses = db.fetch_all(
            "SELECT id, user_id, name, status FROM courses ORDER BY id"
        )
        self.assertEqual(
            [(row["user_id"], row["name"], row["status"]) for row in courses],
            [(0, "旧课程", "active"), (7, "旧完成课", "completed")],
        )
        phases = db.fetch_all(
            """
            SELECT user_id, course_id, phase_number, outcome
            FROM course_learning_phases
            ORDER BY course_id, phase_number
            """
        )
        self.assertEqual(len(phases), 2)
        self.assertEqual(phases[0]["user_id"], 0)
        self.assertEqual(phases[0]["outcome"], "")
        self.assertEqual(phases[1]["user_id"], 7)
        self.assertEqual(phases[1]["outcome"], "completed")


if __name__ == "__main__":
    unittest.main()
