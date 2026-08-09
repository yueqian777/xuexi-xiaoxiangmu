import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import chatgpt_explanation_schema as schema
from services import chatgpt_explanation_task_service as task_service
from services import chatgpt_inbox_service as inbox_service


class ChatGptInboxServiceTest(unittest.TestCase):
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
        self.user_id = 21
        self.deck_id, self.slide_ids = self._seed_deck()
        created = task_service.create_task_packages(
            self.user_id,
            self.deck_id,
            range_mode="custom",
            slide_numbers=[1, 2],
        )
        self.manifest = created["packages"][0]["manifest"]

    def _seed_deck(self):
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, 'deck.pdf', 'FIR', 'Signals', 'deck.pdf', 2)
            """,
            (self.user_id,),
        )
        slide_ids = [
            db.insert_and_get_id(
                "INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text) VALUES (?, ?, ?, ?, ?)",
                (self.user_id, deck_id, number, f"Slide {number}", f"Text {number}"),
            )
            for number in (1, 2)
        ]
        return deck_id, slide_ids

    def _payload(self, *, result_id="result-inbox", slide_ids=None):
        selected = self.slide_ids if slide_ids is None else list(slide_ids)
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
                    "slide_number": number_by_id[slide_id],
                    "explanation": f"Explanation {number_by_id[slide_id]}",
                }
                for slide_id in selected
            ],
        }

    @staticmethod
    def _bytes(payload):
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def test_scan_discovers_supported_json_result(self):
        path = inbox_service.save_uploaded_result(
            self._bytes(self._payload()),
            filename="explanation_result.json",
        )

        items = inbox_service.scan(self.user_id, stable_seconds=0)

        self.assertEqual(len(items), 1)
        self.assertEqual(Path(items[0]["path"]), path)
        self.assertEqual(items[0]["status"], "ready")
        self.assertTrue(items[0]["report"]["complete"])

    def test_scan_ignores_partial_download_and_temporary_files(self):
        inbox = inbox_service.inbox_directory()
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "result.json.crdownload").write_bytes(b"partial")
        (inbox / "result.tmp.json").write_bytes(b"partial")
        (inbox / ".hidden-result.json").write_bytes(b"partial")

        items = inbox_service.scan(self.user_id, stable_seconds=0)

        self.assertEqual(items, [])

    def test_invalid_json_does_not_block_other_valid_files(self):
        inbox_service.save_uploaded_result(b"{broken", filename="broken.json")
        inbox_service.save_uploaded_result(
            self._bytes(self._payload(result_id="result-valid")),
            filename="valid.json",
        )

        items = inbox_service.scan(self.user_id, stable_seconds=0)

        self.assertEqual(len(items), 2)
        self.assertEqual({item["status"] for item in items}, {"invalid", "ready"})

    def test_recent_file_waits_until_stable_before_reading(self):
        inbox_service.save_uploaded_result(self._bytes(self._payload()), filename="recent.json")

        items = inbox_service.scan(self.user_id, stable_seconds=60)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "waiting_stable")

    def test_same_size_rewrite_after_preview_is_rolled_back_to_inbox(self):
        source = inbox_service.save_uploaded_result(self._bytes(self._payload()), filename="race.json")
        original_preview = inbox_service.result_service.preview_result

        def preview_then_rewrite(user_id, payload):
            report = original_preview(user_id, payload)
            before = source.stat()
            original = source.read_bytes()
            changed = original.replace(b"Explanation 1", b"Explanation X", 1)
            self.assertEqual(len(changed), len(original))
            source.write_bytes(changed)
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
            return report

        with patch.object(
            inbox_service.result_service,
            "preview_result",
            side_effect=preview_then_rewrite,
        ):
            outcome = inbox_service.import_inbox_result(self.user_id, source)

        imported_rows = db.fetch_all(
            "SELECT explanation FROM slide_explanations WHERE user_id = ? ORDER BY id",
            (self.user_id,),
        )
        self.assertEqual(outcome["archive_status"], "failed")
        self.assertTrue(source.is_file())
        self.assertFalse(Path(outcome["archive_path"]).exists())
        self.assertEqual(imported_rows[0]["explanation"], "Explanation 1")
        self.assertIn(b"Explanation X", source.read_bytes())

    def test_successful_import_moves_file_to_auditable_imported_path(self):
        source = inbox_service.save_uploaded_result(self._bytes(self._payload()), filename="result.json")

        outcome = inbox_service.import_inbox_result(self.user_id, source)

        archived = Path(outcome["archive_path"])
        self.assertEqual(outcome["status"], "imported")
        self.assertFalse(source.exists())
        self.assertTrue(archived.is_file())
        self.assertTrue(archived.parent.name.startswith(self.manifest["task_id"][:24] + "-"))
        self.assertEqual(archived.parent.parent.name, f"user_{self.user_id}")
        self.assertTrue(archived.name.startswith("result-inbox-"))
        self.assertEqual(archived.suffix, ".json")
        result_row = db.fetch_one(
            "SELECT source_path FROM chatgpt_explanation_results WHERE user_id = ? AND result_id = ?",
            (self.user_id, "result-inbox"),
        )
        self.assertEqual(Path(result_row["source_path"]), archived)

    def test_distinct_valid_result_ids_never_collide_after_filename_normalization(self):
        first_source = inbox_service.save_uploaded_result(
            self._bytes(self._payload(result_id="result_a")), filename="first.json"
        )
        second_source = inbox_service.save_uploaded_result(
            self._bytes(self._payload(result_id="result__a")), filename="second.json"
        )

        first = inbox_service.import_inbox_result(self.user_id, first_source)
        second = inbox_service.import_inbox_result(self.user_id, second_source)

        self.assertEqual(first["archive_status"], "archived")
        self.assertEqual(second["archive_status"], "archived")
        self.assertNotEqual(first["archive_path"], second["archive_path"])
        self.assertTrue(Path(first["archive_path"]).is_file())
        self.assertTrue(Path(second["archive_path"]).is_file())
        self.assertEqual(
            db.fetch_one(
                "SELECT COUNT(*) AS count FROM chatgpt_explanation_results WHERE user_id = ?",
                (self.user_id,),
            )["count"],
            2,
        )

    def test_archive_failure_keeps_source_and_retry_does_not_write_twice(self):
        source = inbox_service.save_uploaded_result(self._bytes(self._payload()), filename="locked.json")

        with patch(
            "services.chatgpt_inbox_service.os.rename",
            side_effect=OSError("file is locked"),
        ):
            failed = inbox_service.import_inbox_result(self.user_id, source)

        stored_after_failure = db.fetch_one(
            "SELECT source_path FROM chatgpt_explanation_results WHERE user_id = ? AND result_id = ?",
            (self.user_id, "result-inbox"),
        )
        self.assertEqual(failed["archive_status"], "failed")
        self.assertTrue(source.is_file())
        self.assertEqual(Path(stored_after_failure["source_path"]), source)

        retried = inbox_service.import_inbox_result(self.user_id, source)
        explanation_count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )["count"]
        stored_after_retry = db.fetch_one(
            "SELECT source_path FROM chatgpt_explanation_results WHERE user_id = ? AND result_id = ?",
            (self.user_id, "result-inbox"),
        )
        self.assertEqual(retried["status"], "skipped")
        self.assertEqual(retried["archive_status"], "archived")
        self.assertEqual(explanation_count, 2)
        self.assertEqual(Path(stored_after_retry["source_path"]), Path(retried["archive_path"]))

    def test_reappearing_imported_result_is_skipped_without_new_rows(self):
        payload = self._bytes(self._payload())
        first = inbox_service.save_uploaded_result(payload, filename="first.json")
        inbox_service.import_inbox_result(self.user_id, first)
        inbox_service.save_uploaded_result(payload, filename="again.json")

        items = inbox_service.scan(self.user_id, stable_seconds=0)
        count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )["count"]

        self.assertEqual(items[0]["status"], "already_imported")
        self.assertEqual(count, 2)

    def test_imported_duplicate_stays_skipped_after_deck_content_changes(self):
        payload = self._bytes(self._payload(result_id="result-old-deck"))
        first = inbox_service.save_uploaded_result(payload, filename="first-old.json")
        inbox_service.import_inbox_result(self.user_id, first)
        inbox_service.save_uploaded_result(payload, filename="again-old.json")
        db.execute(
            "UPDATE ppt_slides SET slide_text = 'changed deck' WHERE id = ?",
            (self.slide_ids[0],),
        )

        items = inbox_service.scan(self.user_id, stable_seconds=0)

        self.assertEqual(items[0]["status"], "already_imported")
        self.assertTrue(items[0]["report"]["duplicate_payload_matches"])

    def test_failed_file_is_not_silently_deleted(self):
        path = inbox_service.save_uploaded_result(b"{broken", filename="broken.json")

        items = inbox_service.scan(self.user_id, stable_seconds=0)

        self.assertEqual(items[0]["status"], "invalid")
        self.assertTrue(path.exists())

    def test_oversized_json_is_rejected_before_parsing(self):
        path = inbox_service.save_uploaded_result(
            b"x" * (schema.MAX_RESULT_BYTES + 1),
            filename="too-large.json",
            allow_invalid=True,
        )

        items = inbox_service.scan(self.user_id, stable_seconds=0)

        self.assertTrue(path.exists())
        self.assertEqual(items[0]["status"], "invalid")
        self.assertTrue(any("过大" in error for error in items[0]["errors"]))

    def test_auto_import_only_accepts_complete_result(self):
        inbox_service.save_uploaded_result(
            self._bytes(self._payload(result_id="result-partial", slide_ids=self.slide_ids[:1])),
            filename="partial.json",
        )

        partial_items = inbox_service.scan(self.user_id, stable_seconds=0, auto_import=True)
        self.assertEqual(partial_items[0]["status"], "partial")
        self.assertEqual(
            db.fetch_one("SELECT COUNT(*) AS count FROM slide_explanations")["count"],
            0,
        )

        inbox_service.save_uploaded_result(
            self._bytes(self._payload(result_id="result-complete")),
            filename="complete.json",
        )
        complete_items = inbox_service.scan(self.user_id, stable_seconds=0, auto_import=True)
        self.assertTrue(any(item["status"] == "imported" for item in complete_items))
        self.assertEqual(
            db.fetch_one("SELECT COUNT(*) AS count FROM slide_explanations")["count"],
            2,
        )

    def test_manual_upload_filename_cannot_escape_inbox(self):
        path = inbox_service.save_uploaded_result(
            self._bytes(self._payload()),
            filename="../../evil/result.json",
        )

        self.assertEqual(path.parent.resolve(), inbox_service.inbox_directory().resolve())
        self.assertNotIn("..", path.name)


if __name__ == "__main__":
    unittest.main()
