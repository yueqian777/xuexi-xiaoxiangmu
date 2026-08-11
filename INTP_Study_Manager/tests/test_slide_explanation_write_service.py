import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import chatgpt_explanation_schema as bridge_schema
from services import chatgpt_explanation_task_service as task_service
from services import slide_explanation_write_service as writer
from repositories import ppt_repository


class SlideExplanationWriteServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.data_dir / "study_manager.db"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()
        self.user_id = 31
        self.deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, 'fir.pdf', 'FIR', 'Signals', 'fir.pdf', 3)
            """,
            (self.user_id,),
        )
        self.slide_ids = []
        for number in range(1, 4):
            self.slide_ids.append(
                db.insert_and_get_id(
                    """
                    INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (self.user_id, self.deck_id, number, f"Slide {number}", f"Text {number}"),
                )
            )
        db.insert_and_get_id(
            """
            INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
            VALUES (?, ?, 'Legacy API', 'old version')
            """,
            (self.user_id, self.slide_ids[0]),
        )

    def _slides(self):
        return [
            {
                "slide_id": slide_id,
                "slide_number": number,
                "explanation": f"解释 {number}",
            }
            for number, slide_id in enumerate(self.slide_ids, start=1)
        ]

    def test_single_append_preserves_old_version_and_model(self):
        result = writer.append_slide_explanation(
            self.user_id,
            self.slide_ids[0],
            1,
            "新的 MCP 讲解",
            model="ChatGPT MCP",
            deck_id=self.deck_id,
        )

        rows = db.fetch_all(
            "SELECT id, model, explanation FROM slide_explanations WHERE slide_id = ? ORDER BY id ASC",
            (self.slide_ids[0],),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["explanation"], "old version")
        self.assertEqual(rows[1]["model"], "ChatGPT MCP")
        self.assertEqual(result["explanation_id"], rows[1]["id"])
        self.assertEqual(result["slide_id"], self.slide_ids[0])

    def test_writer_uses_the_database_local_timestamp_format(self):
        result = writer.append_slide_explanation(
            self.user_id,
            self.slide_ids[1],
            2,
            "timestamp format",
            model="ChatGPT MCP",
            deck_id=self.deck_id,
        )

        row = db.fetch_one(
            "SELECT created_at FROM slide_explanations WHERE id = ?",
            (result["explanation_id"],),
        )
        self.assertEqual(result["created_at"], row["created_at"])
        self.assertIn(" ", result["created_at"])
        self.assertNotIn("T", result["created_at"])

    def test_latest_queries_prefer_the_later_append_with_mixed_legacy_timestamps(self):
        legacy_id = db.insert_and_get_id(
            """
            INSERT INTO slide_explanations (
                user_id, slide_id, model, explanation, created_at
            )
            VALUES (?, ?, 'ChatGPT MCP', 'legacy T timestamp', '2099-01-01T00:00:00')
            """,
            (self.user_id, self.slide_ids[1]),
        )
        later_id = ppt_repository.add_slide_explanation(
            self.user_id,
            self.slide_ids[1],
            "Later API",
            "later append",
        )
        self.assertGreater(later_id, legacy_id)

        latest = ppt_repository.latest_explanation(self.user_id, self.slide_ids[1])
        latest_by_slide = ppt_repository.latest_explanations_by_slide_ids(
            self.user_id, [self.slide_ids[1]]
        )

        self.assertEqual(latest["id"], later_id)
        self.assertEqual(latest["explanation"], "later append")
        self.assertEqual(latest_by_slide[self.slide_ids[1]]["id"], later_id)

    def test_slide_number_and_explicit_deck_mismatch_are_rejected(self):
        with self.assertRaises(writer.SlideExplanationWriteError) as mismatch:
            writer.append_slide_explanation(
                self.user_id,
                self.slide_ids[0],
                2,
                "wrong number",
                model="ChatGPT MCP",
            )
        self.assertEqual(mismatch.exception.code, "slide_number_mismatch")

        with self.assertRaises(writer.SlideExplanationWriteError) as wrong_deck:
            writer.append_slide_explanation(
                self.user_id,
                self.slide_ids[0],
                1,
                "wrong deck",
                model="ChatGPT MCP",
                deck_id=self.deck_id + 999,
            )
        self.assertEqual(wrong_deck.exception.code, "deck_mismatch")

    def test_cross_user_slide_is_rejected(self):
        with self.assertRaises(writer.SlideExplanationWriteError) as caught:
            writer.append_slide_explanation(
                self.user_id + 1,
                self.slide_ids[0],
                1,
                "not mine",
                model="ChatGPT MCP",
                deck_id=self.deck_id,
            )
        self.assertIn(caught.exception.code, {"not_found", "ownership_mismatch"})

    def test_empty_overlong_and_invalid_unicode_are_rejected(self):
        invalid_values = [
            ("   ", "empty_explanation"),
            ("x" * (bridge_schema.MAX_EXPLANATION_CHARS + 1), "explanation_too_long"),
            ("bad\ud800", "invalid_unicode"),
        ]
        for explanation, expected_code in invalid_values:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(writer.SlideExplanationWriteError) as caught:
                    writer.append_slide_explanation(
                        self.user_id,
                        self.slide_ids[0],
                        1,
                        explanation,
                        model="ChatGPT MCP",
                    )
                self.assertEqual(caught.exception.code, expected_code)

    def test_stale_expected_fingerprint_is_rejected(self):
        fingerprint = task_service.deck_fingerprint(self.user_id, self.deck_id)
        db.execute(
            "UPDATE ppt_slides SET slide_text = 'changed' WHERE user_id = ? AND id = ?",
            (self.user_id, self.slide_ids[0]),
        )

        with self.assertRaises(writer.SlideExplanationWriteError) as caught:
            writer.append_slide_explanation(
                self.user_id,
                self.slide_ids[0],
                1,
                "stale",
                model="ChatGPT MCP",
                deck_id=self.deck_id,
                expected_deck_fingerprint=fingerprint,
            )
        self.assertEqual(caught.exception.code, "stale_deck_fingerprint")

    def test_batch_is_atomic_and_returns_ids_in_input_order(self):
        outcome = writer.append_slide_explanations(
            self.user_id,
            self._slides(),
            model="ChatGPT MCP",
            deck_id=self.deck_id,
            max_items=25,
        )

        self.assertEqual(outcome["count"], 3)
        self.assertEqual(len(outcome["explanation_ids"]), 3)
        self.assertEqual(
            outcome["explanation_ids"],
            [item["explanation_id"] for item in outcome["items"]],
        )
        self.assertEqual(
            [item["slide_id"] for item in outcome["items"]],
            self.slide_ids,
        )

    def test_batch_rejects_duplicates_mixed_decks_and_limit(self):
        duplicate = self._slides()[:2]
        duplicate[1]["slide_id"] = duplicate[0]["slide_id"]
        with self.assertRaises(writer.SlideExplanationWriteError) as caught:
            writer.append_slide_explanations(
                self.user_id, duplicate, model="ChatGPT MCP", deck_id=self.deck_id
            )
        self.assertEqual(caught.exception.code, "duplicate_slide_id")

        other_deck = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, file_path, slide_count)
            VALUES (?, 'other.pdf', 'Other', 'other.pdf', 1)
            """,
            (self.user_id,),
        )
        other_slide = db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title)
            VALUES (?, ?, 1, 'Other 1')
            """,
            (self.user_id, other_deck),
        )
        mixed = self._slides()[:1] + [
            {"slide_id": other_slide, "slide_number": 1, "explanation": "other"}
        ]
        with self.assertRaises(writer.SlideExplanationWriteError) as caught:
            writer.append_slide_explanations(self.user_id, mixed, model="ChatGPT MCP")
        self.assertEqual(caught.exception.code, "mixed_decks")

        with self.assertRaises(writer.SlideExplanationWriteError) as caught:
            writer.append_slide_explanations(
                self.user_id,
                self._slides(),
                model="ChatGPT MCP",
                deck_id=self.deck_id,
                max_items=2,
            )
        self.assertEqual(caught.exception.code, "too_many_slides")

    def test_validation_failure_rolls_back_every_insert(self):
        before = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )["count"]
        invalid = self._slides()
        invalid[-1]["slide_number"] = 999

        with self.assertRaises(writer.SlideExplanationWriteError):
            writer.append_slide_explanations(
                self.user_id,
                invalid,
                model="ChatGPT MCP",
                deck_id=self.deck_id,
            )

        after = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )["count"]
        self.assertEqual(after, before)

    def test_supplied_transaction_is_reused_and_rolls_back_with_caller(self):
        with self.assertRaises(RuntimeError):
            with db.write_transaction() as conn:
                writer.append_slide_explanation(
                    self.user_id,
                    self.slide_ids[1],
                    2,
                    "inside caller transaction",
                    model="ChatGPT Web",
                    deck_id=self.deck_id,
                    conn=conn,
                )
                raise RuntimeError("rollback caller")

        row = db.fetch_one(
            "SELECT id FROM slide_explanations WHERE slide_id = ? AND explanation = ?",
            (self.slide_ids[1], "inside caller transaction"),
        )
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
