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

    def _build_package(
        self,
        *,
        package_type="ppt_explanation_share",
        privacy_mode="public_ppt_explanation_only",
        omit_slide=False,
        slide_markdown=None,
    ):
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
                    slide_markdown
                    or "# Slide 001: FIR basics\n\n## Slide Content\n\npublic text\n\n## AI Explanation\n\npublic explanation",
                )
            archive.writestr("images/slide-001.png", b"fake-png")
        return zip_path

    def _build_multi_deck_package(self):
        zip_path = self.data_dir / "multi-share.zip"
        manifest = {
            "package_type": "ppt_explanation_share",
            "version": "1.0",
            "package_id": "ppt-share-multi-test",
            "subject": "Shared aggregate",
            "deck_title": "Two public decks",
            "exported_at": "2026-06-08T09:00:00",
            "privacy_mode": "public_ppt_explanation_only",
            "included_sections": ["slide_text", "slide_images", "ai_explanations"],
            "excluded_sections": ["slide_questions", "knowledge_cards", "review_tasks"],
            "decks": [
                {
                    "source_deck_id": 11,
                    "subject": "Signals",
                    "deck_title": "FIR filters",
                    "filename": "fir.pptx",
                    "slide_count": 2,
                    "slides": [
                        {
                            "slide_number": 1,
                            "title": "FIR basics",
                            "markdown_path": "decks/fir/slides/slide-001.md",
                            "image_path": "decks/fir/images/slide-001.png",
                        },
                        {
                            "slide_number": 2,
                            "title": "Windows",
                            "markdown_path": "decks/fir/slides/slide-002.md",
                            "image_path": "decks/fir/images/slide-002.png",
                        },
                    ],
                },
                {
                    "deck_id": 12,
                    "subject": "Control",
                    "deck_title": "PID loops",
                    "filename": "pid.pptx",
                    "slide_count": 1,
                    "slides": [
                        {
                            "slide_number": 1,
                            "title": "PID basics",
                            "markdown_path": "decks/pid/slides/slide-001.md",
                            "image_path": "decks/pid/images/slide-001.png",
                        }
                    ],
                },
            ],
        }
        markdown_by_path = {
            "decks/fir/slides/slide-001.md": "# Slide 001: FIR basics\n\n## Slide Content\n\nfir text 1\n\n## AI Explanation\n\nfir explanation 1",
            "decks/fir/slides/slide-002.md": "# Slide 002: Windows\n\n## Slide Content\n\nfir text 2\n\n## AI Explanation\n\nfir explanation 2",
            "decks/pid/slides/slide-001.md": "# Slide 001: PID basics\n\n## PPT/PDF 页面文字\n\npid text 1\n\n## AI 逐页讲解\n\npid explanation 1",
        }
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            for markdown_path, markdown in markdown_by_path.items():
                archive.writestr(markdown_path, markdown)
            archive.writestr("decks/fir/images/slide-001.png", b"fake-png-fir-1")
            archive.writestr("decks/fir/images/slide-002.png", b"fake-png-fir-2")
            archive.writestr("decks/fir/attachments/original.pptx", b"original")
            archive.writestr("decks/pid/images/slide-001.png", b"fake-png-pid-1")
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

    def test_import_preserves_explanation_that_starts_with_markdown_heading(self):
        zip_path = self._build_package(
            slide_markdown=(
                "# Slide 001: FIR basics\n\n"
                "## PPT/PDF 页面文字\n\n"
                "public text\n\n"
                "## 页面图片\n\n"
                "![页面图片](../images/slide-001.png)\n\n"
                "## AI 逐页讲解\n\n"
                "## 第 1 页：FIR basics\n\n"
                "### 本页核心\n"
                "- explanation body\n\n"
                "## 自动摘要\n\n"
                "summary should not be imported as explanation\n\n"
                "## 导航\n\n"
                "- 下一页：无"
            )
        )

        result = ppt_explanation_import_service.import_share_package(self.user_id, zip_path)

        slide = db.fetch_one("SELECT * FROM ppt_slides WHERE deck_id = ?", (result["deck_id"],))
        explanation = db.fetch_one("SELECT * FROM slide_explanations WHERE slide_id = ?", (slide["id"],))
        self.assertIn("## 第 1 页：FIR basics", explanation["explanation"])
        self.assertIn("explanation body", explanation["explanation"])
        self.assertNotIn("summary should not be imported", explanation["explanation"])

    def test_multi_deck_package_previews_and_imports_each_deck_without_learning_state(self):
        zip_path = self._build_multi_deck_package()

        preview = ppt_explanation_import_service.preview_share_package(self.user_id, zip_path)
        result = ppt_explanation_import_service.import_share_package(self.user_id, zip_path)

        self.assertEqual(preview["package_id"], "ppt-share-multi-test")
        self.assertEqual(preview["deck_count"], 2)
        self.assertEqual(preview["slide_count"], 3)
        self.assertTrue(preview["has_original"])
        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["package_id"], "ppt-share-multi-test")
        self.assertEqual(result["deck_count"], 2)
        self.assertEqual(len(result["deck_ids"]), 2)
        self.assertEqual(result["deck_id"], result["deck_ids"][0])

        decks = db.fetch_all("SELECT * FROM ppt_decks WHERE user_id = ? ORDER BY id", (self.user_id,))
        self.assertEqual([deck["title"] for deck in decks], ["FIR filters", "PID loops"])
        self.assertEqual([deck["subject"] for deck in decks], ["Signals", "Control"])
        self.assertEqual([deck["filename"] for deck in decks], ["fir.pptx", "pid.pptx"])
        self.assertEqual([deck["slide_count"] for deck in decks], [2, 1])

        fir_slide = db.fetch_one("SELECT * FROM ppt_slides WHERE deck_id = ? AND slide_number = 2", (result["deck_ids"][0],))
        self.assertEqual(fir_slide["title"], "Windows")
        self.assertIn("fir text 2", fir_slide["slide_text"])
        self.assertTrue(Path(fir_slide["image_path"]).exists())
        fir_explanation = db.fetch_one("SELECT * FROM slide_explanations WHERE slide_id = ?", (fir_slide["id"],))
        self.assertIn("fir explanation 2", fir_explanation["explanation"])

        pid_slide = db.fetch_one("SELECT * FROM ppt_slides WHERE deck_id = ? AND slide_number = 1", (result["deck_ids"][1],))
        self.assertEqual(pid_slide["slide_text"], "pid text 1")
        pid_explanation = db.fetch_one("SELECT * FROM slide_explanations WHERE slide_id = ?", (pid_slide["id"],))
        self.assertEqual(pid_explanation["explanation"], "pid explanation 1")

        package = db.fetch_one("SELECT * FROM import_packages WHERE package_id = ?", ("ppt-share-multi-test",))
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

    def test_orphan_package_record_does_not_block_reimport(self):
        zip_path = self._build_package()
        db.insert_and_get_id(
            """
            INSERT INTO import_packages (
                user_id, package_id, package_type, package_version, privacy_mode,
                subject, title, source_filename, manifest_json
            )
            VALUES (?, 'ppt-share-test', 'ppt_explanation_share', '1.0', 'public_ppt_explanation_only',
                    'Signals', 'FIR filters', 'share.zip', '{}')
            """,
            (self.user_id,),
        )

        preview = ppt_explanation_import_service.preview_share_package(self.user_id, zip_path)
        result = ppt_explanation_import_service.import_share_package(
            self.user_id,
            zip_path,
            duplicate_policy="skip",
        )

        self.assertFalse(preview["already_imported"])
        self.assertEqual(result["status"], "imported")
        self.assertIsNotNone(result["deck_id"])


if __name__ == "__main__":
    unittest.main()
