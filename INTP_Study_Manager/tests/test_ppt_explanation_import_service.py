import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import db
from services import ppt_explanation_import_service


class PptExplanationImportServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
            patch.object(ppt_explanation_import_service, "DATA_DIR", self.data_dir),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()
        self.user_id = 3

    def _build_package(self, *, package_type="ppt_explanation_share", privacy_mode="public_ppt_explanation_only", omit_slide=False):
        zip_path = self.data_dir / "share.zip"
        manifest = {
            "package_type": package_type,
            "version": "1.0",
            "package_id": "ppt-share-test",
            "subject": "Signals",
            "deck_title": "FIR filters",
            "exported_at": "2026-06-06T21:00:00",
            "slide_count": 1,
            "privacy_mode": privacy_mode,
            "included_sections": ["slide_text", "slide_images", "ai_explanations"],
            "excluded_sections": ["slide_questions", "knowledge_cards", "review_tasks"],
            "slides": [
                {
                    "slide_number": 1,
                    "title": "FIR basics",
                    "markdown_path": "slides/slide-001.md",
                    "image_path": "images/slide-001.png",
                }
            ],
        }
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            if not omit_slide:
                archive.writestr(
                    "slides/slide-001.md",
                    "# Slide 001: FIR basics\n\n## Slide Content\n\npublic text\n\n## AI Explanation\n\npublic explanation",
                )
            archive.writestr("images/slide-001.png", b"fake-png")
        return zip_path

    def test_preview_rejects_invalid_or_incomplete_packages(self):
        with self.assertRaises(ValueError):
            ppt_explanation_import_service.preview_share_package(
                self.user_id,
                self._build_package(package_type="other"),
            )
        with self.assertRaises(ValueError):
            ppt_explanation_import_service.preview_share_package(
                self.user_id,
                self._build_package(privacy_mode="private_learning_data"),
            )
        with self.assertRaises(ValueError):
            ppt_explanation_import_service.preview_share_package(
                self.user_id,
                self._build_package(omit_slide=True),
            )

    def test_import_valid_zip_creates_deck_slides_explanations_assets_and_package_record(self):
        zip_path = self._build_package()

        preview = ppt_explanation_import_service.preview_share_package(self.user_id, zip_path)
        result = ppt_explanation_import_service.import_share_package(self.user_id, zip_path)

        self.assertEqual(preview["package_id"], "ppt-share-test")
        deck = db.fetch_one("SELECT * FROM ppt_decks WHERE id = ?", (result["deck_id"],))
        self.assertEqual(deck["subject"], "Signals")
        self.assertEqual(deck["title"], "FIR filters")
        self.assertEqual(deck["source_type"], "ppt_explanation_share")
        self.assertEqual(deck["source_package_id"], "ppt-share-test")
        slide = db.fetch_one("SELECT * FROM ppt_slides WHERE deck_id = ?", (result["deck_id"],))
        self.assertEqual(slide["slide_number"], 1)
        self.assertTrue(Path(slide["image_path"]).exists())
        explanation = db.fetch_one("SELECT * FROM slide_explanations WHERE slide_id = ?", (slide["id"],))
        self.assertEqual(explanation["model"], "imported_share")
        self.assertIn("public explanation", explanation["explanation"])
        package = db.fetch_one("SELECT * FROM import_packages WHERE package_id = ?", ("ppt-share-test",))
        self.assertIsNotNone(package)
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS count FROM slide_questions")["count"], 0)
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS count FROM knowledge_cards")["count"], 0)
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS count FROM review_tasks")["count"], 0)

    def test_duplicate_package_can_skip_or_import_copy(self):
        zip_path = self._build_package()
        first = ppt_explanation_import_service.import_share_package(self.user_id, zip_path)
        skipped = ppt_explanation_import_service.import_share_package(self.user_id, zip_path, duplicate_policy="skip")
        copied = ppt_explanation_import_service.import_share_package(self.user_id, zip_path, duplicate_policy="copy")

        self.assertEqual(skipped["status"], "skipped")
        self.assertNotEqual(first["deck_id"], copied["deck_id"])
        self.assertEqual(
            db.fetch_one("SELECT COUNT(*) AS count FROM ppt_decks WHERE user_id = ?", (self.user_id,))["count"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
