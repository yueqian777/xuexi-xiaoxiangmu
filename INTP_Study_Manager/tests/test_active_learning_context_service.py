import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import active_learning_context_service as context_service
from services.ppt_reader_state import reader_position_setting_key


class ActiveLearningContextServiceTest(unittest.TestCase):
    def setUp(self):
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

        self.user_id = 7
        self.deck_id, self.slide_ids = self._seed_deck(self.user_id, "FIR 数字滤波器")
        self.other_deck_id, self.other_slide_ids = self._seed_deck(self.user_id, "IIR 数字滤波器")
        self.foreign_user_id = 9
        self.foreign_deck_id, self.foreign_slide_ids = self._seed_deck(
            self.foreign_user_id,
            "其他用户课件",
        )

    def _seed_deck(self, user_id: int, title: str) -> tuple[int, list[int]]:
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, ?, ?, '信号与系统', ?, 2)
            """,
            (int(user_id), f"{title}.pdf", title, f"{title}.pdf"),
        )
        slide_ids = [
            db.insert_and_get_id(
                """
                INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(user_id), deck_id, number, f"第 {number} 页", f"正文 {number}"),
            )
            for number in (1, 2)
        ]
        return deck_id, slide_ids

    def test_set_active_deck_persists_owned_deck_metadata(self):
        context = context_service.set_active_deck(self.user_id, self.deck_id)

        self.assertTrue(context["active"])
        self.assertEqual(context["user_id"], self.user_id)
        self.assertEqual(context["deck_id"], self.deck_id)
        self.assertEqual(context["deck_title"], "FIR 数字滤波器")
        self.assertEqual(context["subject"], "信号与系统")
        self.assertIsNone(context["slide_id"])
        self.assertEqual(context["context_version"], 1)

        row = db.fetch_one(
            "SELECT user_id, value FROM app_settings WHERE key = ?",
            (f"user:{self.user_id}:active_learning_context",),
        )
        self.assertEqual(row["user_id"], self.user_id)
        self.assertEqual(json.loads(row["value"])["deck_id"], self.deck_id)

    def test_set_active_slide_accepts_number_and_stores_slide_id(self):
        context_service.set_active_deck(self.user_id, self.deck_id)

        context = context_service.set_active_slide(
            self.user_id,
            self.deck_id,
            slide_number=2,
        )

        self.assertEqual(context["slide_id"], self.slide_ids[1])
        self.assertEqual(context["slide_number"], 2)

    def test_set_active_slide_accepts_id_and_stores_slide_number(self):
        context = context_service.set_active_slide(
            self.user_id,
            self.deck_id,
            slide_id=self.slide_ids[0],
        )

        self.assertEqual(context["deck_id"], self.deck_id)
        self.assertEqual(context["slide_id"], self.slide_ids[0])
        self.assertEqual(context["slide_number"], 1)

    def test_context_is_isolated_by_user(self):
        context_service.set_active_slide(self.user_id, self.deck_id, slide_number=2)
        context_service.set_active_slide(
            self.foreign_user_id,
            self.foreign_deck_id,
            slide_number=1,
        )

        first = context_service.get_active_context(self.user_id)
        second = context_service.get_active_context(self.foreign_user_id)

        self.assertEqual(first["deck_id"], self.deck_id)
        self.assertEqual(first["slide_number"], 2)
        self.assertEqual(second["deck_id"], self.foreign_deck_id)
        self.assertEqual(second["slide_number"], 1)

    def test_switching_deck_clears_slide_question_and_selection(self):
        context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)
        context_service.set_active_selection(
            self.user_id,
            "explanation",
            "窗函数决定旁瓣",
            slide_id=self.slide_ids[0],
            context_before="前文",
            context_after="后文",
        )

        context = context_service.set_active_deck(self.user_id, self.other_deck_id)

        self.assertEqual(context["deck_id"], self.other_deck_id)
        self.assertIsNone(context["slide_id"])
        self.assertIsNone(context["slide_number"])
        self.assertIsNone(context["active_question_id"])
        self.assertIsNone(context["selection"])

    def test_set_active_slide_rejects_slide_from_another_deck(self):
        with self.assertRaisesRegex(ValueError, "幻灯片"):
            context_service.set_active_slide(
                self.user_id,
                self.deck_id,
                slide_id=self.other_slide_ids[0],
            )

    def test_set_active_deck_rejects_cross_user_deck(self):
        with self.assertRaisesRegex(ValueError, "PPT"):
            context_service.set_active_deck(self.user_id, self.foreign_deck_id)

    def test_same_context_is_idempotent_and_does_not_touch_setting_timestamp(self):
        first = context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)
        key = f"user:{self.user_id}:active_learning_context"
        db.execute("UPDATE app_settings SET updated_at = 'sentinel' WHERE key = ?", (key,))

        second = context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)
        row = db.fetch_one("SELECT updated_at, value FROM app_settings WHERE key = ?", (key,))

        self.assertEqual(row["updated_at"], "sentinel")
        self.assertEqual(second["updated_at"], first["updated_at"])
        self.assertEqual(json.loads(row["value"])["updated_at"], first["updated_at"])

    def test_deleted_active_deck_returns_inactive_without_guessing(self):
        context_service.set_active_deck(self.user_id, self.deck_id)
        db.execute("DELETE FROM ppt_decks WHERE user_id = ? AND id = ?", (self.user_id, self.deck_id))

        self.assertEqual(context_service.get_active_context(self.user_id), {"active": False})

    def test_deleted_active_slide_returns_inactive_without_guessing(self):
        context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)
        db.execute(
            "DELETE FROM ppt_slides WHERE user_id = ? AND id = ?",
            (self.user_id, self.slide_ids[0]),
        )

        self.assertEqual(context_service.get_active_context(self.user_id), {"active": False})

    def test_malformed_setting_returns_inactive(self):
        db.execute(
            "INSERT INTO app_settings (key, user_id, value) VALUES (?, ?, 'not-json')",
            (f"user:{self.user_id}:active_learning_context", self.user_id),
        )

        self.assertEqual(context_service.get_active_context(self.user_id), {"active": False})

    def test_selection_can_be_set_and_cleared(self):
        context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)

        selected = context_service.set_active_selection(
            self.user_id,
            "question",
            "为什么频谱会泄漏？",
            slide_id=self.slide_ids[0],
            question_id=None,
            context_before="前文",
            context_after="后文",
        )
        cleared = context_service.clear_active_selection(self.user_id)

        self.assertEqual(
            selected["selection"],
            {
                "source": "question",
                "text": "为什么频谱会泄漏？",
                "slide_id": self.slide_ids[0],
                "question_id": None,
                "context_before": "前文",
                "context_after": "后文",
            },
        )
        self.assertIsNone(cleared["selection"])
        self.assertIsNone(cleared["active_question_id"])

    def test_selection_rejects_non_active_slide(self):
        context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)

        with self.assertRaisesRegex(ValueError, "当前页"):
            context_service.set_active_selection(
                self.user_id,
                "explanation",
                "不属于当前页",
                slide_id=self.slide_ids[1],
            )

    def test_deleted_active_question_clears_stale_question_selection_on_read(self):
        question_id = db.insert_and_get_id(
            """
            INSERT INTO slide_questions (user_id, slide_id, question, answer, model)
            VALUES (?, ?, '为什么？', '因为。', 'test')
            """,
            (self.user_id, self.slide_ids[0]),
        )
        context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)
        context_service.set_active_selection(
            self.user_id,
            "question",
            "因为",
            slide_id=self.slide_ids[0],
            question_id=question_id,
        )
        db.execute(
            "DELETE FROM slide_questions WHERE user_id = ? AND id = ?",
            (self.user_id, question_id),
        )

        context = context_service.get_active_context(self.user_id)

        self.assertTrue(context["active"])
        self.assertIsNone(context["active_question_id"])
        self.assertIsNone(context["selection"])

    def test_malformed_or_oversized_persisted_selection_is_not_returned(self):
        context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)
        key = context_service.active_context_setting_key(self.user_id)
        row = db.fetch_one("SELECT value FROM app_settings WHERE key = ?", (key,))
        payload = json.loads(row["value"])
        payload["selection"] = {
            "source": "question",
            "text": "x" * (context_service.MAX_SELECTION_TEXT_LENGTH + 1),
            "slide_id": self.slide_ids[0],
            "question_id": None,
            "context_before": "",
            "context_after": "",
        }
        db.execute(
            "UPDATE app_settings SET value = ? WHERE key = ?",
            (json.dumps(payload), key),
        )

        self.assertIsNone(context_service.get_active_context(self.user_id)["selection"])

    def test_context_writes_do_not_modify_reader_position_setting(self):
        reader_key = reader_position_setting_key(self.user_id)
        reader_payload = json.dumps({"deck_id": self.deck_id, "slide_number": 2})
        db.execute(
            "INSERT INTO app_settings (key, user_id, value) VALUES (?, ?, ?)",
            (reader_key, self.user_id, reader_payload),
        )

        context_service.set_active_slide(self.user_id, self.deck_id, slide_number=1)

        row = db.fetch_one("SELECT value FROM app_settings WHERE key = ?", (reader_key,))
        self.assertEqual(row["value"], reader_payload)

    def test_context_refuses_to_take_over_another_users_namespaced_setting(self):
        key = context_service.active_context_setting_key(self.user_id)
        db.execute(
            "INSERT INTO app_settings (key, user_id, value) VALUES (?, ?, '{}')",
            (key, self.foreign_user_id),
        )

        with self.assertRaisesRegex(ValueError, "用户范围"):
            context_service.set_active_deck(self.user_id, self.deck_id)

        row = db.fetch_one(
            "SELECT user_id, value FROM app_settings WHERE key = ?", (key,)
        )
        self.assertEqual(row, {"user_id": self.foreign_user_id, "value": "{}"})

    def test_context_identifiers_reject_bool_and_fractional_numbers(self):
        invalid_calls = [
            lambda: context_service.get_active_context(True),
            lambda: context_service.set_active_deck(self.user_id, 1.2),
            lambda: context_service.set_active_slide(
                self.user_id, self.deck_id, slide_number=1.2
            ),
        ]
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValueError):
                    call()


if __name__ == "__main__":
    unittest.main()
