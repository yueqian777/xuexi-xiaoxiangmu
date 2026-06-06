import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import db
from services import ppt_explanation_export_service


class PptExplanationExportServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
            patch.object(ppt_explanation_export_service, "DATA_DIR", self.data_dir),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()
        self.user_id = 5

    def _seed_deck(self):
        original = self.data_dir / "uploads" / "user_5" / "deck.pdf"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"%PDF original")
        image = self.data_dir / "page_images" / "slide-001.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"fake-png")
        secret = self.data_dir / "api_keys_user_5.enc.json"
        secret.write_text("secret", encoding="utf-8")
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, 'deck.pdf', 'FIR filters', 'Signals', ?, 1)
            """,
            (self.user_id, str(original)),
        )
        slide_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text, image_path)
            VALUES (?, ?, 1, 'FIR basics', 'public slide text', ?)
            """,
            (self.user_id, deck_id, str(image)),
        )
        db.insert_and_get_id(
            "INSERT INTO slide_explanations (user_id, slide_id, model, explanation) VALUES (?, ?, 'model', 'public AI explanation')",
            (self.user_id, slide_id),
        )
        db.insert_and_get_id(
            "INSERT INTO slide_questions (user_id, slide_id, question, answer, model) VALUES (?, ?, 'private question', 'private answer', 'model')",
            (self.user_id, slide_id),
        )
        db.insert_and_get_id(
            "INSERT INTO knowledge_cards (user_id, subject, topic, one_sentence) VALUES (?, 'Signals', 'Private card', 'private card')",
            (self.user_id,),
        )
        return deck_id

    def test_export_public_zip_contains_only_public_ppt_explanation_content(self):
        deck_id = self._seed_deck()

        result = ppt_explanation_export_service.export_deck_share_package(
            self.user_id,
            deck_id,
            include_original=False,
        )

        zip_path = Path(result["zip_path"])
        self.assertTrue(zip_path.exists())
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            self.assertIn("README.md", names)
            self.assertIn("_Deck_Home.md", names)
            self.assertIn("manifest.json", names)
            self.assertIn("slides/slide-001.md", names)
            self.assertIn("images/slide-001.png", names)
            self.assertNotIn("attachments/original.pdf", names)
            self.assertTrue(all(not name.endswith(".enc.json") for name in names))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            slide_md = archive.read("slides/slide-001.md").decode("utf-8")

        self.assertEqual(manifest["package_type"], "ppt_explanation_share")
        self.assertEqual(manifest["privacy_mode"], "public_ppt_explanation_only")
        self.assertIn("slide_questions", manifest["excluded_sections"])
        self.assertIn("knowledge_cards", manifest["excluded_sections"])
        self.assertIn("public slide text", slide_md)
        self.assertIn("public AI explanation", slide_md)
        for forbidden in ["private question", "private answer", "Private card", "插问", "错因", "掌握度", "复习任务"]:
            self.assertNotIn(forbidden, slide_md)

    def test_original_file_is_only_included_when_requested(self):
        deck_id = self._seed_deck()

        result = ppt_explanation_export_service.export_deck_share_package(
            self.user_id,
            deck_id,
            include_original=True,
        )

        with zipfile.ZipFile(result["zip_path"]) as archive:
            self.assertIn("attachments/original.pdf", set(archive.namelist()))


if __name__ == "__main__":
    unittest.main()
