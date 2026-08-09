import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import chatgpt_explanation_result_service as result_service
from services import chatgpt_explanation_schema as schema
from services import chatgpt_explanation_task_service as task_service


class ChatGptExplanationResultServiceTest(unittest.TestCase):
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
        self.user_id = 12
        self.deck_id, self.slide_ids = self._seed_deck()
        created = task_service.create_task_packages(
            self.user_id,
            self.deck_id,
            range_mode="custom",
            slide_numbers=[1, 2, 3],
        )
        self.package = created["packages"][0]
        self.manifest = self.package["manifest"]

    def _seed_deck(self):
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, 'deck.pdf', 'FIR', 'Signals', 'deck.pdf', 3)
            """,
            (self.user_id,),
        )
        slide_ids = []
        for number in range(1, 4):
            slide_ids.append(
                db.insert_and_get_id(
                    """
                    INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (self.user_id, deck_id, number, f"Slide {number}", f"Text {number}"),
                )
            )
        db.insert_and_get_id(
            "INSERT INTO slide_explanations (user_id, slide_id, model, explanation) VALUES (?, ?, 'API old', '旧讲解')",
            (self.user_id, slide_ids[0]),
        )
        return deck_id, slide_ids

    def _payload(self, *, result_id="result-first", slide_ids=None):
        selected_ids = self.slide_ids if slide_ids is None else list(slide_ids)
        number_by_id = {slide_id: index for index, slide_id in enumerate(self.slide_ids, start=1)}
        return {
            "package_type": "intp_chatgpt_explanation_result",
            "version": "1.0",
            "result_id": result_id,
            "task_id": self.manifest["task_id"],
            "deck_id": self.deck_id,
            "deck_fingerprint": self.manifest["deck_fingerprint"],
            "generator": "chatgpt_web",
            "generated_at": "2026-08-09T12:00:00+08:00",
            "slides": [
                {
                    "slide_id": slide_id,
                    "slide_number": number_by_id.get(slide_id, 999),
                    "explanation": f"# ChatGPT 讲解 {number_by_id.get(slide_id, 999)}",
                }
                for slide_id in selected_ids
            ],
        }

    @staticmethod
    def _bytes(payload):
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def test_valid_result_passes_all_checks(self):
        report = result_service.preview_result(self.user_id, self._bytes(self._payload()))

        self.assertTrue(report["hard_valid"])
        self.assertTrue(report["complete"])
        self.assertTrue(report["auto_import_allowed"])
        self.assertEqual(report["valid_count"], 3)
        self.assertEqual(report["missing_slide_ids"], [])
        self.assertEqual(report["unknown_slide_ids"], [])

    def test_unknown_task_id_is_rejected(self):
        payload = self._payload()
        payload["task_id"] = "task-20990101-unknown"

        report = result_service.preview_result(self.user_id, self._bytes(payload))

        self.assertFalse(report["hard_valid"])
        self.assertTrue(any("task_id" in error for error in report["errors"]))

    def test_wrong_deck_id_is_rejected(self):
        payload = self._payload()
        payload["deck_id"] = self.deck_id + 1

        report = result_service.preview_result(self.user_id, self._bytes(payload))

        self.assertFalse(report["hard_valid"])
        self.assertTrue(any("deck_id" in error for error in report["errors"]))

    def test_wrong_fingerprint_is_rejected(self):
        payload = self._payload()
        payload["deck_fingerprint"] = "sha256:" + "0" * 64

        report = result_service.preview_result(self.user_id, self._bytes(payload))

        self.assertFalse(report["hard_valid"])
        self.assertFalse(report["fingerprint_ok"])

    def test_unknown_slide_id_is_rejected(self):
        payload = self._payload()
        payload["slides"].append(
            {"slide_id": 999999, "slide_number": 99, "explanation": "unknown"}
        )

        report = result_service.preview_result(self.user_id, self._bytes(payload))

        self.assertFalse(report["hard_valid"])
        self.assertEqual(report["unknown_slide_ids"], [999999])

    def test_slide_id_number_mismatch_is_rejected(self):
        payload = self._payload()
        payload["slides"][0]["slide_number"] = 2

        report = result_service.preview_result(self.user_id, self._bytes(payload))

        self.assertFalse(report["hard_valid"])
        self.assertTrue(any("slide_number" in error for error in report["errors"]))

    def test_malformed_and_non_utf8_json_return_errors_without_crashing(self):
        malformed = result_service.preview_result(self.user_id, b"{not-json")
        non_utf8 = result_service.preview_result(self.user_id, b"\xff\xfe\x00")

        self.assertFalse(malformed["hard_valid"])
        self.assertFalse(non_utf8["hard_valid"])
        self.assertTrue(malformed["errors"])
        self.assertTrue(non_utf8["errors"])

    def test_wrong_package_type_and_unsupported_version_are_rejected(self):
        wrong_type = self._payload()
        wrong_type["package_type"] = "ppt_explanation_share"
        wrong_version = self._payload()
        wrong_version["version"] = "2.0"

        type_report = result_service.preview_result(self.user_id, self._bytes(wrong_type))
        version_report = result_service.preview_result(self.user_id, self._bytes(wrong_version))

        self.assertTrue(any("package_type" in error for error in type_report["errors"]))
        self.assertTrue(any("version" in error for error in version_report["errors"]))

    def test_duplicate_json_keys_are_rejected(self):
        raw = self._bytes(self._payload()).decode("utf-8")
        raw = raw.replace(
            '"package_type": "intp_chatgpt_explanation_result",',
            '"package_type": "intp_chatgpt_explanation_result", "package_type": "evil",',
            1,
        )

        report = result_service.preview_result(self.user_id, raw.encode("utf-8"))

        self.assertFalse(report["hard_valid"])
        self.assertTrue(any("重复" in error for error in report["errors"]))

    def test_nonfinite_json_number_is_rejected(self):
        raw = self._bytes(self._payload()).decode("utf-8")
        raw = raw.replace('"deck_id": ' + str(self.deck_id), '"deck_id": NaN', 1)

        report = result_service.preview_result(self.user_id, raw.encode("utf-8"))

        self.assertFalse(report["hard_valid"])
        self.assertTrue(any("无效数值" in error for error in report["errors"]))

    def test_normal_import_appends_chatgpt_web_explanations(self):
        outcome = result_service.import_result(self.user_id, self._bytes(self._payload()))

        rows = db.fetch_all(
            "SELECT slide_id, model, explanation FROM slide_explanations WHERE user_id = ? ORDER BY id",
            (self.user_id,),
        )
        self.assertEqual(outcome["status"], "imported")
        self.assertEqual(len(rows), 4)
        self.assertEqual([row["model"] for row in rows[-3:]], ["ChatGPT Web"] * 3)

    def test_import_never_overwrites_old_explanation(self):
        result_service.import_result(self.user_id, self._bytes(self._payload()))

        rows = db.fetch_all(
            "SELECT model, explanation FROM slide_explanations WHERE user_id = ? AND slide_id = ? ORDER BY id",
            (self.user_id, self.slide_ids[0]),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"model": "API old", "explanation": "旧讲解"})
        self.assertEqual(rows[1]["model"], "ChatGPT Web")

    def test_import_rolls_back_result_and_all_slides_when_one_insert_fails(self):
        db.execute(
            f"""
            CREATE TRIGGER reject_second_chatgpt_explanation
            BEFORE INSERT ON slide_explanations
            WHEN NEW.model = 'ChatGPT Web' AND NEW.slide_id = {int(self.slide_ids[1])}
            BEGIN
                SELECT RAISE(ABORT, 'forced rollback');
            END
            """
        )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "forced rollback"):
            result_service.import_result(self.user_id, self._bytes(self._payload()))

        explanation_count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )["count"]
        result_count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM chatgpt_explanation_results WHERE user_id = ?",
            (self.user_id,),
        )["count"]
        task_status = db.fetch_one(
            "SELECT status FROM chatgpt_explanation_tasks WHERE user_id = ? AND task_id = ?",
            (self.user_id, self.manifest["task_id"]),
        )["status"]
        self.assertEqual(explanation_count, 1)
        self.assertEqual(result_count, 0)
        self.assertEqual(task_status, "waiting_result")

    def test_same_result_id_is_idempotent_but_new_result_id_adds_a_version(self):
        first = self._payload(result_id="result-one")
        second = self._payload(result_id="result-two")

        result_service.import_result(self.user_id, self._bytes(first))
        duplicate = result_service.import_result(self.user_id, self._bytes(first))
        result_service.import_result(self.user_id, self._bytes(second))

        count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )["count"]
        result_count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM chatgpt_explanation_results WHERE user_id = ?",
            (self.user_id,),
        )["count"]
        self.assertEqual(duplicate["status"], "skipped")
        self.assertEqual(count, 7)
        self.assertEqual(result_count, 2)

    def test_duplicate_id_allows_formatting_changes_but_rejects_changed_content(self):
        payload = self._payload(result_id="result-semantic-duplicate")
        result_service.import_result(self.user_id, self._bytes(payload))
        reformatted = json.dumps(payload, ensure_ascii=False, indent=4, sort_keys=True).encode(
            "utf-8"
        )

        skipped = result_service.import_result(self.user_id, reformatted)
        changed = json.loads(json.dumps(payload, ensure_ascii=False))
        changed["slides"][0]["explanation"] = "被替换的内容"

        self.assertEqual(skipped["status"], "skipped")
        self.assertTrue(skipped["duplicate_payload_matches"])
        with self.assertRaisesRegex(ValueError, "内容.*不一致"):
            result_service.import_result(self.user_id, self._bytes(changed))

    def test_partial_result_is_recognized_and_requires_explicit_permission(self):
        payload = self._payload(slide_ids=self.slide_ids[:2])

        report = result_service.preview_result(self.user_id, self._bytes(payload))

        self.assertTrue(report["hard_valid"])
        self.assertFalse(report["complete"])
        self.assertFalse(report["auto_import_allowed"])
        self.assertEqual(report["valid_count"], 2)
        self.assertEqual(report["missing_slide_ids"], [self.slide_ids[2]])
        with self.assertRaisesRegex(ValueError, "部分"):
            result_service.import_result(self.user_id, self._bytes(payload), allow_partial=False)

    def test_partial_and_complete_import_update_task_status(self):
        partial_payload = self._payload(result_id="result-partial", slide_ids=self.slide_ids[:2])

        partial = result_service.import_result(
            self.user_id,
            self._bytes(partial_payload),
            allow_partial=True,
        )
        partial_task = db.fetch_one(
            "SELECT status FROM chatgpt_explanation_tasks WHERE user_id = ? AND task_id = ?",
            (self.user_id, self.manifest["task_id"]),
        )
        complete_payload = self._payload(result_id="result-complete")
        complete = result_service.import_result(self.user_id, self._bytes(complete_payload))
        complete_task = db.fetch_one(
            "SELECT status FROM chatgpt_explanation_tasks WHERE user_id = ? AND task_id = ?",
            (self.user_id, self.manifest["task_id"]),
        )

        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial_task["status"], "partial")
        self.assertEqual(complete["status"], "imported")
        self.assertEqual(complete_task["status"], "imported")

    def test_result_for_another_user_cannot_access_task_or_deck(self):
        report = result_service.preview_result(999, self._bytes(self._payload()))

        self.assertFalse(report["hard_valid"])
        self.assertTrue(any("task_id" in error for error in report["errors"]))

    def test_old_task_is_rejected_after_current_deck_content_changes(self):
        db.execute(
            "UPDATE ppt_slides SET slide_text = 'new deck version' WHERE id = ?",
            (self.slide_ids[1],),
        )

        report = result_service.preview_result(self.user_id, self._bytes(self._payload()))

        self.assertFalse(report["hard_valid"])
        self.assertFalse(report["fingerprint_ok"])
        self.assertTrue(any("当前 PPT" in error for error in report["errors"]))

    def test_excessive_explanation_length_and_duplicate_slide_are_rejected(self):
        too_long = self._payload()
        too_long["slides"][0]["explanation"] = "x" * (schema.MAX_EXPLANATION_CHARS + 1)
        duplicate_slide = self._payload()
        duplicate_slide["slides"].append(dict(duplicate_slide["slides"][0]))

        length_report = result_service.preview_result(self.user_id, self._bytes(too_long))
        duplicate_report = result_service.preview_result(self.user_id, self._bytes(duplicate_slide))

        self.assertFalse(length_report["hard_valid"])
        self.assertFalse(duplicate_report["hard_valid"])
        self.assertTrue(any("过长" in error for error in length_report["errors"]))
        self.assertTrue(any("重复" in error for error in duplicate_report["errors"]))


if __name__ == "__main__":
    unittest.main()
