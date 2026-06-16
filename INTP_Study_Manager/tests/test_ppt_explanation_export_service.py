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

    def _seed_deck(
        self,
        *,
        filename="deck.pdf",
        title="FIR filters",
        subject="Signals",
        slide_text="public slide text",
        explanation="public AI explanation",
        image_name="slide-001.png",
    ):
        original = self.data_dir / "uploads" / "user_5" / filename
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"%PDF original")
        image = self.data_dir / "page_images" / image_name
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"fake-png")
        secret = self.data_dir / "api_keys_user_5.enc.json"
        secret.write_text("secret", encoding="utf-8")
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (self.user_id, filename, title, subject, str(original)),
        )
        slide_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text, image_path)
            VALUES (?, ?, 1, 'FIR basics', ?, ?)
            """,
            (self.user_id, deck_id, slide_text, str(image)),
        )
        db.insert_and_get_id(
            "INSERT INTO slide_explanations (user_id, slide_id, model, explanation) VALUES (?, ?, 'model', ?)",
            (self.user_id, slide_id, explanation),
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

    def test_export_share_package_includes_bookmarks_and_ai_structure(self):
        deck_id = self._seed_deck()
        slide = db.fetch_one("SELECT * FROM ppt_slides WHERE deck_id = ?", (deck_id,))
        db.execute(
            """
            UPDATE ppt_decks
            SET outline = '滤波器学习主线'
            WHERE id = ?
            """,
            (deck_id,),
        )
        db.insert_and_get_id(
            """
            INSERT INTO ppt_sections (
                user_id, deck_id, section_index, title, topic, core_question, summary,
                key_terms_json, prerequisite_concepts_json, start_slide, end_slide
            )
            VALUES (?, ?, 1, '第一块：低通滤波器', '滤波器', '为什么低通能保留慢变信号？',
                    '先建立频率选择的直觉。', '["低通", "截止频率"]', '["频域"]', 1, 1)
            """,
            (self.user_id, deck_id),
        )
        db.execute(
            """
            UPDATE ppt_slides
            SET section_index = 1,
                page_type = '公式页',
                one_sentence_summary = '低通滤波器保留低频。',
                slide_role = '核心定义',
                key_points = '区分通带与阻带',
                bookmark_enabled = 1,
                bookmark_title = '重点公式页'
            WHERE id = ?
            """,
            (slide["id"],),
        )

        result = ppt_explanation_export_service.export_deck_share_package(
            self.user_id,
            deck_id,
            include_original=False,
        )

        with zipfile.ZipFile(result["zip_path"]) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            deck_entry = manifest["decks"][0]
            slide_entry = deck_entry["slides"][0]
            slide_md = archive.read(slide_entry["markdown_path"]).decode("utf-8")

        self.assertIn("bookmarks", manifest["included_sections"])
        self.assertIn("document_structure", manifest["included_sections"])
        self.assertEqual(deck_entry["document_structure"]["outline"], "滤波器学习主线")
        self.assertEqual(deck_entry["document_structure"]["sections"][0]["title"], "第一块：低通滤波器")
        self.assertEqual(deck_entry["document_structure"]["sections"][0]["key_terms"], ["低通", "截止频率"])
        self.assertEqual(slide_entry["bookmark"], {"enabled": True, "title": "重点公式页"})
        self.assertEqual(slide_entry["page_metadata"]["page_type"], "公式页")
        self.assertEqual(slide_entry["page_metadata"]["one_sentence_summary"], "低通滤波器保留低频。")
        self.assertIn("## 书签", slide_md)
        self.assertIn("重点公式页", slide_md)
        self.assertIn("## AI 分块", slide_md)
        self.assertIn("第一块：低通滤波器", slide_md)
        self.assertIn("页面类型：公式页", slide_md)

    def test_export_multi_deck_share_package_uses_deck_scoped_paths_and_readable_markdown(self):
        first_deck_id = self._seed_deck()
        second_deck_id = self._seed_deck(
            filename="deck-two.pdf",
            title="IIR filters",
            slide_text="second public slide text",
            explanation="second public AI explanation",
            image_name="slide-002.png",
        )

        result = ppt_explanation_export_service.export_decks_share_package(
            self.user_id,
            [first_deck_id, second_deck_id],
            include_original=False,
        )

        with zipfile.ZipFile(result["zip_path"]) as archive:
            names = set(archive.namelist())
            self.assertIn("README.md", names)
            self.assertIn("_Deck_Home.md", names)
            self.assertIn("manifest.json", names)
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            deck_entries = manifest["decks"]
            slide_paths = [
                slide["markdown_path"]
                for deck in deck_entries
                for slide in deck["slides"]
            ]
            image_paths = [
                slide["image_path"]
                for deck in deck_entries
                for slide in deck["slides"]
            ]
            first_slide_md = archive.read(slide_paths[0]).decode("utf-8")
            second_slide_md = archive.read(slide_paths[1]).decode("utf-8")

        self.assertEqual(result["deck_count"], 2)
        self.assertEqual(result["slide_count"], 2)
        self.assertEqual(manifest["deck_count"], 2)
        self.assertEqual(manifest["slide_count"], 2)
        self.assertEqual([deck["deck_id"] for deck in deck_entries], [first_deck_id, second_deck_id])
        self.assertTrue(all(path.startswith("decks/deck-") for path in slide_paths))
        self.assertTrue(all("/slides/slide-001.md" in path for path in slide_paths))
        self.assertTrue(all(path in names for path in slide_paths))
        self.assertTrue(all(path in names for path in image_paths))
        self.assertIn("- 科目：Signals", first_slide_md)
        self.assertIn("- PPT：FIR filters", first_slide_md)
        self.assertIn("- 页码：1", first_slide_md)
        self.assertIn("## PPT/PDF 页面文字", first_slide_md)
        self.assertIn("## AI 逐页讲解", first_slide_md)
        self.assertIn("second public slide text", second_slide_md)
        self.assertIn("second public AI explanation", second_slide_md)
        for forbidden in ["private question", "private answer", "Private card", "插问", "错因", "掌握度", "复习任务"]:
            self.assertNotIn(forbidden, first_slide_md)
            self.assertNotIn(forbidden, second_slide_md)


if __name__ == "__main__":
    unittest.main()
