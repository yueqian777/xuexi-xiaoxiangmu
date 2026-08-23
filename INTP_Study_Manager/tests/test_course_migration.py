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

    def test_invalid_links_and_card_provenance_are_repaired_idempotently(self) -> None:
        deck_course = db.insert_and_get_id(
            "INSERT INTO courses (user_id, name, status) VALUES (51, '规范课', 'active')"
        )
        label_course = db.insert_and_get_id(
            "INSERT INTO courses (user_id, name, status) VALUES (51, '生成标签', 'active')"
        )
        foreign_course = db.insert_and_get_id(
            "INSERT INTO courses (user_id, name, status) VALUES (99, '外部课程', 'active')"
        )
        phase_id = db.insert_and_get_id(
            """
            INSERT INTO course_learning_phases (user_id, course_id, phase_number)
            VALUES (999, ?, 1)
            """,
            (deck_course,),
        )
        summary_id = db.insert_and_get_id(
            """
            INSERT INTO course_summaries (user_id, course_id)
            VALUES (999, ?)
            """,
            (deck_course,),
        )
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, filename, title, subject, file_path, course_id
            )
            VALUES (51, 'canonical.pdf', '规范资料', '旧科目标签', 'canonical.pdf', ?)
            """,
            (deck_course,),
        )
        session_id = db.insert_and_get_id(
            """
            INSERT INTO study_sessions (
                user_id, date, subject, title, main_question, course_id
            )
            VALUES (51, '2026-01-01', '规范课', '来源学习记录', '为什么？', ?)
            """,
            (deck_course,),
        )
        bad_deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, filename, title, subject, file_path, course_id
            )
            VALUES (51, 'bad.pdf', '错误绑定资料', '资料修复课', 'bad.pdf', ?)
            """,
            (foreign_course,),
        )
        bad_session_id = db.insert_and_get_id(
            """
            INSERT INTO study_sessions (
                user_id, date, subject, title, main_question, course_id
            )
            VALUES (51, '2026-01-02', '记录修复课', '错误绑定记录', '为什么？', 999999)
            """
        )
        deck_card = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, one_sentence, source_deck_id, course_id
            )
            VALUES (51, '生成标签', '资料来源卡', '结论', ?, ?)
            """,
            (deck_id, foreign_course),
        )
        session_card = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, one_sentence, source_session_id, course_id
            )
            VALUES (51, '生成标签', '记录来源卡', '结论', ?, 999999)
            """,
            (session_id,),
        )
        orphan_card = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, one_sentence, course_id
            )
            VALUES (51, '生成标签', '无来源卡', '结论', ?)
            """,
            (foreign_course,),
        )

        for _ in range(2):
            db._INITIALIZED_DATABASE_PATH = None
            db.init_db()

        bad_deck = db.fetch_one(
            """
            SELECT d.course_id, c.user_id AS course_user_id, c.name AS course_name
            FROM ppt_decks d JOIN courses c ON c.id = d.course_id
            WHERE d.id = ?
            """,
            (bad_deck_id,),
        )
        bad_session = db.fetch_one(
            """
            SELECT s.course_id, c.user_id AS course_user_id, c.name AS course_name
            FROM study_sessions s JOIN courses c ON c.id = s.course_id
            WHERE s.id = ?
            """,
            (bad_session_id,),
        )
        cards = {
            row["id"]: row["course_id"]
            for row in db.fetch_all(
                "SELECT id, course_id FROM knowledge_cards WHERE id IN (?, ?, ?)",
                (deck_card, session_card, orphan_card),
            )
        }

        self.assertEqual(bad_deck["course_user_id"], 51)
        self.assertEqual(bad_deck["course_name"], "资料修复课")
        self.assertEqual(bad_session["course_user_id"], 51)
        self.assertEqual(bad_session["course_name"], "记录修复课")
        self.assertEqual(cards[deck_card], deck_course)
        self.assertEqual(cards[session_card], deck_course)
        self.assertEqual(cards[orphan_card], label_course)
        self.assertIsNone(
            db.fetch_one(
                "SELECT id FROM courses WHERE user_id = 51 AND TRIM(name) = '旧科目标签'"
            )
        )
        self.assertEqual(
            db.fetch_one(
                "SELECT user_id FROM course_learning_phases WHERE id = ?",
                (phase_id,),
            )["user_id"],
            51,
        )
        self.assertEqual(
            db.fetch_one(
                "SELECT user_id FROM course_summaries WHERE id = ?",
                (summary_id,),
            )["user_id"],
            51,
        )

    def test_duplicate_active_backfill_uses_unicode_normalized_survivor(self) -> None:
        older_id = db.insert_and_get_id(
            """
            INSERT INTO courses (user_id, name, status, created_at, updated_at)
            VALUES (61, '通信原理', 'active', '2025-01-01', '2025-06-01')
            """
        )
        survivor_id = db.insert_and_get_id(
            """
            INSERT INTO courses (user_id, name, status, created_at, updated_at)
            VALUES (61, '\u3000通信原理\u3000', 'active', '2026-01-01', '2026-06-01')
            """
        )
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, filename, title, subject, file_path, course_id
            ) VALUES (61, 'legacy.pdf', '旧课件', '\u3000通信原理\u3000', 'legacy.pdf', NULL)
            """
        )
        session_id = db.insert_and_get_id(
            """
            INSERT INTO study_sessions (
                user_id, date, subject, title, main_question, course_id
            ) VALUES (61, '2026-08-23', '\u00a0通信原理\u00a0', '旧学习记录', '为什么？', NULL)
            """
        )

        snapshots: list[tuple[list[tuple[int, str]], int, int, int]] = []
        for _ in range(2):
            db._INITIALIZED_DATABASE_PATH = None
            db.init_db()
            courses = db.fetch_all(
                """
                SELECT id, status
                FROM courses
                WHERE user_id = 61 AND name = '通信原理'
                ORDER BY id
                """
            )
            snapshots.append(
                (
                    [(int(row["id"]), str(row["status"])) for row in courses],
                    int(db.fetch_one("SELECT course_id FROM ppt_decks WHERE id = ?", (deck_id,))["course_id"]),
                    int(db.fetch_one("SELECT course_id FROM study_sessions WHERE id = ?", (session_id,))["course_id"]),
                    int(
                        db.fetch_one(
                            """
                            SELECT COUNT(*) AS count
                            FROM course_learning_phases
                            WHERE user_id = 61
                            """
                        )["count"]
                    ),
                )
            )

        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(
            snapshots[0],
            ([(older_id, "archived"), (survivor_id, "active")], survivor_id, survivor_id, 2),
        )
        index = db.fetch_one(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_courses_user_active_name_unique'
            """
        )
        self.assertIn("WHERE status = 'active'", str(index["sql"]))


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
        completed = db.fetch_one(
            "SELECT completed_at FROM courses WHERE user_id = 7 AND name = '旧完成课'"
        )
        self.assertTrue(completed["completed_at"])

    def test_terminal_timestamp_prefers_existing_learning_phase_end(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    name TEXT,
                    status TEXT
                )
                """
            )
            course_id = conn.execute(
                """
                INSERT INTO courses (user_id, name, status)
                VALUES (7, '阶段课程', '已完成')
                """
            ).lastrowid
            conn.execute(
                """
                CREATE TABLE course_learning_phases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER,
                    ended_at TEXT,
                    outcome TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO course_learning_phases (course_id, ended_at, outcome)
                VALUES (?, '2025-07-01 18:30:00', 'completed')
                """,
                (course_id,),
            )

        db.init_db()

        course = db.fetch_one(
            "SELECT completed_at FROM courses WHERE id = ?",
            (course_id,),
        )
        self.assertEqual(course["completed_at"], "2025-07-01 18:30:00")

    def test_duplicate_legacy_active_courses_are_deduplicated_without_deletion(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    name TEXT,
                    status TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            archived_course_id = conn.execute(
                """
                INSERT INTO courses (user_id, name, status, created_at, updated_at)
                VALUES (7, '信号与系统', 'active', '2025-01-01', '2025-06-01')
                """
            ).lastrowid
            active_course_id = conn.execute(
                """
                INSERT INTO courses (user_id, name, status, created_at, updated_at)
                VALUES (7, '\u3000信号与系统\u3000', 'active', '2026-01-01', '2026-06-01')
                """
            ).lastrowid
            other_user_course_id = conn.execute(
                """
                INSERT INTO courses (user_id, name, status, created_at, updated_at)
                VALUES (8, '信号与系统', 'active', '2026-02-01', '2026-07-01')
                """
            ).lastrowid
            unnamed_course_id = conn.execute(
                """
                INSERT INTO courses (user_id, name, status, created_at, updated_at)
                VALUES (9, '\u3000\u00a0\t', 'active', '2026-03-01', '2026-08-01')
                """
            ).lastrowid
            conn.execute(
                """
                CREATE TABLE course_learning_phases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    course_id INTEGER,
                    ended_at TEXT,
                    outcome TEXT
                )
                """
            )
            archived_phase_id = conn.execute(
                """
                INSERT INTO course_learning_phases (
                    user_id, course_id, ended_at, outcome
                ) VALUES (999, ?, '', '')
                """,
                (archived_course_id,),
            ).lastrowid

        for _ in range(2):
            db._INITIALIZED_DATABASE_PATH = None
            db.init_db()

        courses = db.fetch_all(
            """
            SELECT id, status, completed_at
            FROM courses
            WHERE user_id = 7 AND TRIM(name) = '信号与系统'
            ORDER BY id
            """
        )
        self.assertEqual(len(courses), 2)
        self.assertEqual([row["status"] for row in courses], ["archived", "active"])
        self.assertEqual(courses[0]["id"], archived_course_id)
        self.assertEqual(courses[1]["id"], active_course_id)
        archived = db.fetch_one(
            "SELECT archived_at FROM courses WHERE id = ?",
            (courses[0]["id"],),
        )
        self.assertTrue(archived["archived_at"])
        phases = db.fetch_all(
            """
            SELECT course_id, ended_at, outcome
            FROM course_learning_phases
            WHERE user_id = 7
            ORDER BY course_id
            """
        )
        self.assertEqual(len(phases), 2)
        self.assertTrue(phases[0]["ended_at"])
        self.assertEqual(phases[0]["outcome"], "archived")
        self.assertEqual(phases[0]["course_id"], archived_course_id)
        self.assertIsNone(phases[1]["ended_at"])
        repaired_phase = db.fetch_one(
            "SELECT id, user_id, outcome FROM course_learning_phases WHERE id = ?",
            (archived_phase_id,),
        )
        self.assertEqual(
            dict(repaired_phase),
            {"id": archived_phase_id, "user_id": 7, "outcome": "archived"},
        )
        self.assertEqual(
            db.fetch_one(
                "SELECT status FROM courses WHERE id = ? AND user_id = 8",
                (other_user_course_id,),
            )["status"],
            "active",
        )
        self.assertEqual(
            db.fetch_one(
                "SELECT name FROM courses WHERE id = ? AND user_id = 9",
                (unnamed_course_id,),
            )["name"],
            f"未命名课程 {unnamed_course_id}",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO courses (user_id, name, status) VALUES (7, '信号与系统', 'active')"
            )


if __name__ == "__main__":
    unittest.main()
