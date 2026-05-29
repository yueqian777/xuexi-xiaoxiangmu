import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import auth_service, ppt_context_service, ppt_service, review_service


class ConcurrencyHardeningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
            patch.object(ppt_service, "UPLOAD_DIR", self.data_dir / "uploads"),
            patch.object(ppt_service, "PAGE_IMAGE_DIR", self.data_dir / "page_images"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()

    def test_uploaded_deck_paths_are_local_user_scoped_and_unique(self):
        first = io.BytesIO(b"first")
        second = io.BytesIO(b"second")
        first.name = "same.pdf"
        second.name = "same.pdf"

        first_path = ppt_service.save_uploaded_deck(first)
        second_path = ppt_service.save_uploaded_deck(second)

        self.assertNotEqual(first_path, second_path)
        self.assertIn("user_0", str(first_path))
        self.assertEqual(first_path.read_bytes(), b"first")
        self.assertEqual(second_path.read_bytes(), b"second")

    def test_initial_review_tasks_are_idempotent(self):
        user_id = auth_service.require_login().id
        knowledge_id = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (user_id, subject, topic, one_sentence)
            VALUES (?, '数学', '极限', '一句话')
            """,
            (user_id,),
        )

        review_service.create_initial_review_tasks(knowledge_id, "2026-05-28", user_id=user_id)
        review_service.create_initial_review_tasks(knowledge_id, "2026-05-28", user_id=user_id)

        count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM review_tasks WHERE user_id = ? AND knowledge_id = ?",
            (user_id, knowledge_id),
        )
        self.assertEqual(count["count"], 4)

    def test_deck_sections_are_still_scoped_by_explicit_user_id(self):
        alice_id = 1
        bob_id = 2
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, file_path)
            VALUES (?, 'alice.pdf', 'Alice Deck', ?)
            """,
            (alice_id, str(self.data_dir / "uploads" / "user_1" / "alice.pdf")),
        )
        db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title)
            VALUES (?, ?, 1, '第一页')
            """,
            (alice_id, deck_id),
        )
        structure = {
            "outline": "大纲",
            "sections": [
                {
                    "section_index": 1,
                    "title": "第一章",
                    "start_slide": 1,
                    "end_slide": 1,
                }
            ],
            "pages": [{"slide_number": 1, "section_index": 1, "page_type": "正文页"}],
        }

        with self.assertRaises(PermissionError):
            ppt_context_service.save_deck_structure(deck_id, structure, user_id=bob_id)

        ppt_context_service.save_deck_structure(deck_id, structure, user_id=alice_id)

        self.assertEqual(len(ppt_context_service.fetch_deck_sections(deck_id, user_id=alice_id)), 1)
        self.assertEqual(ppt_context_service.fetch_deck_sections(deck_id, user_id=bob_id), [])
        section = db.fetch_one("SELECT user_id FROM ppt_sections WHERE deck_id = ?", (deck_id,))
        self.assertEqual(section["user_id"], alice_id)


if __name__ == "__main__":
    unittest.main()
