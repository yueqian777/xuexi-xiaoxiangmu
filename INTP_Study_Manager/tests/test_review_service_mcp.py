from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import db
from services import review_service


class ReviewServiceMcpTest(unittest.TestCase):
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
        self.user_id = 21
        self.other_user_id = 22

    def _create_task(self, user_id: int, *, mastery: int = 60) -> tuple[int, int]:
        knowledge_id = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, one_sentence, mastery, need_review
            )
            VALUES (?, 'DSP', 'ROC', 'Region of convergence', ?, 1)
            """,
            (user_id, mastery),
        )
        task_id = db.insert_and_get_id(
            """
            INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
            VALUES (?, ?, '2020-01-01', '第 1 天复习')
            """,
            (user_id, knowledge_id),
        )
        return knowledge_id, task_id

    def _create_knowledge(self, user_id: int, *, mastery: int = 60) -> int:
        return db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, one_sentence, mastery, need_review
            )
            VALUES (?, 'DSP', 'ROC', 'Region of convergence', ?, 1)
            """,
            (user_id, mastery),
        )

    def test_submit_review_result_uses_explicit_user_and_returns_mastery_change(self):
        knowledge_id, task_id = self._create_task(self.user_id)

        result = review_service.submit_review_result(self.user_id, task_id, "基本掌握")

        self.assertEqual(result["review_task_id"], task_id)
        self.assertEqual(result["knowledge_id"], knowledge_id)
        self.assertEqual(result["mastery_before"], 60)
        self.assertGreater(result["mastery_after"], 60)
        task = db.fetch_one("SELECT status, result FROM review_tasks WHERE id = ?", (task_id,))
        self.assertEqual(task, {"status": "已完成", "result": "基本掌握"})

    def test_submit_review_result_rejects_invalid_result_without_mutation(self):
        knowledge_id, task_id = self._create_task(self.user_id)

        with self.assertRaises(ValueError):
            review_service.submit_review_result(self.user_id, task_id, "invented result")

        task = db.fetch_one("SELECT status, result FROM review_tasks WHERE id = ?", (task_id,))
        card = db.fetch_one("SELECT mastery FROM knowledge_cards WHERE id = ?", (knowledge_id,))
        self.assertEqual(task, {"status": "待复习", "result": ""})
        self.assertEqual(card["mastery"], 60)

    def test_submit_review_result_rejects_fractional_identifiers_without_mutation(self):
        knowledge_id, task_id = self._create_task(self.user_id)

        with self.assertRaises(ValueError):
            review_service.submit_review_result(self.user_id + 0.2, task_id, "基本掌握")
        with self.assertRaises(ValueError):
            review_service.submit_review_result(self.user_id, task_id + 0.2, "基本掌握")

        task = db.fetch_one("SELECT status FROM review_tasks WHERE id = ?", (task_id,))
        card = db.fetch_one("SELECT mastery FROM knowledge_cards WHERE id = ?", (knowledge_id,))
        self.assertEqual(task["status"], "待复习")
        self.assertEqual(card["mastery"], 60)

    def test_submit_review_result_cannot_mutate_another_users_task(self):
        knowledge_id, task_id = self._create_task(self.other_user_id)

        result = review_service.submit_review_result(self.user_id, task_id, "完全掌握")

        self.assertIsNone(result)
        task = db.fetch_one("SELECT status FROM review_tasks WHERE id = ?", (task_id,))
        card = db.fetch_one("SELECT mastery FROM knowledge_cards WHERE id = ?", (knowledge_id,))
        self.assertEqual(task["status"], "待复习")
        self.assertEqual(card["mastery"], 60)

    def test_repeated_submission_is_idempotent(self):
        knowledge_id, task_id = self._create_task(self.user_id)

        first = review_service.submit_review_result(self.user_id, task_id, "完全掌握")
        second = review_service.submit_review_result(self.user_id, task_id, "完全不会")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        card = db.fetch_one("SELECT mastery FROM knowledge_cards WHERE id = ?", (knowledge_id,))
        self.assertEqual(card["mastery"], first["mastery_after"])
        extra = db.fetch_one(
            "SELECT COUNT(*) AS count FROM review_tasks WHERE user_id = ? AND knowledge_id = ?",
            (self.user_id, knowledge_id),
        )
        self.assertEqual(extra["count"], 1)

    def test_fuzzy_result_creates_one_extra_review_in_the_same_transaction(self):
        knowledge_id, task_id = self._create_task(self.user_id)

        result = review_service.submit_review_result(self.user_id, task_id, "仍然模糊")

        self.assertTrue(result["extra_review"]["created"])
        self.assertEqual(result["extra_review"]["review_stage"], "追加复习：2 天后")
        tasks = db.fetch_all(
            "SELECT status, review_stage FROM review_tasks WHERE user_id = ? AND knowledge_id = ? ORDER BY id",
            (self.user_id, knowledge_id),
        )
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["status"], "已完成")
        self.assertEqual(tasks[1]["status"], "待复习")

    def test_database_failure_rolls_back_task_and_mastery_together(self):
        knowledge_id, task_id = self._create_task(self.user_id)
        db.execute(
            """
            CREATE TRIGGER reject_mastery_update
            BEFORE UPDATE OF mastery ON knowledge_cards
            BEGIN
                SELECT RAISE(ABORT, 'reject mastery update');
            END;
            """
        )

        with self.assertRaises(Exception):
            review_service.submit_review_result(self.user_id, task_id, "基本掌握")

        task = db.fetch_one("SELECT status, result FROM review_tasks WHERE id = ?", (task_id,))
        card = db.fetch_one("SELECT mastery FROM knowledge_cards WHERE id = ?", (knowledge_id,))
        self.assertEqual(task, {"status": "待复习", "result": ""})
        self.assertEqual(card["mastery"], 60)

    def test_legacy_mark_review_result_keeps_login_fallback_and_accepts_explicit_user(self):
        _, first_task = self._create_task(self.user_id)
        _, second_task = self._create_task(self.user_id)

        explicit = review_service.mark_review_result(first_task, "基本掌握", user_id=self.user_id)
        with patch.object(review_service, "require_login", return_value=SimpleNamespace(id=self.user_id)):
            fallback = review_service.mark_review_result(second_task, "基本掌握")

        self.assertEqual(explicit["review_task_id"], first_task)
        self.assertEqual(fallback["review_task_id"], second_task)

    def test_ensure_initial_reviews_join_supplied_transaction(self):
        knowledge_id = self._create_knowledge(self.user_id)

        with self.assertRaisesRegex(RuntimeError, "force outer rollback"):
            with db.write_transaction() as conn:
                review_service.ensure_initial_review_tasks(
                    knowledge_id,
                    "2026-08-11",
                    user_id=self.user_id,
                    conn=conn,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM review_tasks WHERE knowledge_id = ? AND user_id = ?",
                        (knowledge_id, self.user_id),
                    ).fetchone()[0],
                    4,
                )
                raise RuntimeError("force outer rollback")

        self.assertEqual(
            db.fetch_one(
                "SELECT COUNT(*) AS count FROM review_tasks WHERE knowledge_id = ? AND user_id = ?",
                (knowledge_id, self.user_id),
            )["count"],
            0,
        )

    def test_ensure_initial_reviews_repairs_partial_schedule_idempotently(self):
        knowledge_id = self._create_knowledge(self.user_id)
        db.execute(
            """
            INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
            VALUES (?, ?, '2026-08-12', '第 1 天复习')
            """,
            (self.user_id, knowledge_id),
        )

        review_service.ensure_initial_review_tasks(
            knowledge_id,
            "2026-08-11",
            user_id=self.user_id,
        )
        review_service.ensure_initial_review_tasks(
            knowledge_id,
            "2026-08-11",
            user_id=self.user_id,
        )

        tasks = db.fetch_all(
            """
            SELECT review_date, review_stage
            FROM review_tasks
            WHERE user_id = ? AND knowledge_id = ?
            ORDER BY review_date, review_stage
            """,
            (self.user_id, knowledge_id),
        )
        self.assertEqual(
            tasks,
            [
                {"review_date": "2026-08-12", "review_stage": "第 1 天复习"},
                {"review_date": "2026-08-14", "review_stage": "第 3 天复习"},
                {"review_date": "2026-08-18", "review_stage": "第 7 天复习"},
                {"review_date": "2026-08-25", "review_stage": "第 14 天复习"},
            ],
        )

    def test_ensure_initial_reviews_keeps_existing_anchor_when_called_later(self):
        knowledge_id = self._create_knowledge(self.user_id)
        review_service.ensure_initial_review_tasks(
            knowledge_id,
            "2026-08-11",
            user_id=self.user_id,
        )

        review_service.ensure_initial_review_tasks(
            knowledge_id,
            "2026-08-20",
            user_id=self.user_id,
        )

        tasks = db.fetch_all(
            """
            SELECT review_date, review_stage
            FROM review_tasks
            WHERE user_id = ? AND knowledge_id = ?
            ORDER BY review_date, review_stage
            """,
            (self.user_id, knowledge_id),
        )
        self.assertEqual(
            tasks,
            [
                {"review_date": "2026-08-12", "review_stage": "第 1 天复习"},
                {"review_date": "2026-08-14", "review_stage": "第 3 天复习"},
                {"review_date": "2026-08-18", "review_stage": "第 7 天复习"},
                {"review_date": "2026-08-25", "review_stage": "第 14 天复习"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
