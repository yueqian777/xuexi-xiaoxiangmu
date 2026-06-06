import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from repositories import ppt_repository
from services import markdown_export_service


class MarkdownExportServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
            patch.object(markdown_export_service, "DATA_DIR", self.data_dir),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()
        self.user_id = 7

    def _seed_private_data(self):
        session_id = db.insert_and_get_id(
            """
            INSERT INTO study_sessions (user_id, date, subject, chapter, title, main_question)
            VALUES (?, '2026-06-04', 'Signals', 'Z', 'Z review', 'What is ROC?')
            """,
            (self.user_id,),
        )
        first_card = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, core_question, one_sentence, mastery, need_review, source_session_id
            )
            VALUES (?, 'Signals', 'ROC', 'What is ROC?', 'Region of convergence.', 60, 1, ?)
            """,
            (self.user_id, session_id),
        )
        second_card = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (user_id, subject, topic, core_question, one_sentence, mastery, need_review)
            VALUES (?, 'Systems', 'Impulse response', 'What is h[n]?', 'System response.', 75, 0)
            """,
            (self.user_id,),
        )
        db.insert_and_get_id(
            """
            INSERT INTO knowledge_links (user_id, source_knowledge_id, target_knowledge_id, relation_type, relation_note)
            VALUES (?, ?, ?, 'related', 'Cross subject relation')
            """,
            (self.user_id, first_card, second_card),
        )
        db.insert_and_get_id(
            """
            INSERT INTO mistakes (user_id, subject, topic, knowledge_id, original_question, correct_idea, cause_category)
            VALUES (?, 'Signals', 'ROC', ?, 'wrong ROC', 'check poles', 'condition missed')
            """,
            (self.user_id, first_card),
        )
        db.insert_and_get_id(
            """
            INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
            VALUES (?, ?, '2026-06-05', 'day 1')
            """,
            (self.user_id, first_card),
        )
        db.insert_and_get_id(
            """
            INSERT INTO parking_lot (user_id, subject, question, source)
            VALUES (?, 'Signals', 'Open question', 'class')
            """,
            (self.user_id,),
        )
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, 'signals.pdf', 'Signals deck', 'Signals', 'signals.pdf', 1)
            """,
            (self.user_id,),
        )
        slide_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text)
            VALUES (?, ?, 1, 'ROC slide', 'Slide text')
            """,
            (self.user_id, deck_id),
        )
        db.insert_and_get_id(
            """
            INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
            VALUES (?, ?, 'model', 'AI explanation')
            """,
            (self.user_id, slide_id),
        )
        question_id = ppt_repository.create_slide_question_tree_node(
            self.user_id,
            slide_id,
            "Why include unit circle?",
            "Because frequency response.",
            "model",
        )
        db.execute(
            "UPDATE knowledge_cards SET source_deck_id = ?, source_slide_id = ?, source_question_id = ? WHERE id = ?",
            (deck_id, slide_id, question_id, first_card),
        )
        db.execute(
            """
            UPDATE slide_questions
            SET knowledge_id = ?, converted_to_knowledge = 1
            WHERE id = ?
            """,
            (first_card, question_id),
        )
        db.insert_and_get_id(
            "INSERT INTO api_providers (provider_key, user_id, name, provider_type, api_key_env) VALUES ('secret', ?, 'Secret', 'openai', 'OPENAI_API_KEY')",
            (self.user_id,),
        )
        return first_card

    def test_export_private_vault_writes_cards_slides_questions_and_reviews_without_secrets(self):
        card_id = self._seed_private_data()

        result = markdown_export_service.export_obsidian_vault(self.user_id, mode="overwrite")

        root = Path(result["root"])
        self.assertTrue((root / "_Home.md").exists())
        self.assertTrue((root / "_All_Knowledge_Index.md").exists())
        knowledge_files = list((root / "Signals" / "10_Knowledge").glob(f"knowledge-{card_id}-*.md"))
        self.assertEqual(len(knowledge_files), 1)
        card_text = knowledge_files[0].read_text(encoding="utf-8")
        self.assertIn("db_table: knowledge_cards", card_text)
        self.assertIn("[[knowledge-", card_text)

        slide_text = (root / "Signals" / "40_PPT" / "deck-1-Signals-deck" / "slide-001.md").read_text(encoding="utf-8")
        self.assertIn("## Question Tree", slide_text)
        self.assertIn("### Q1 Why include unit circle?", slide_text)
        self.assertIn("[[knowledge-", slide_text)
        self.assertTrue((root / "Signals" / "20_Mistakes").exists())
        self.assertTrue((root / "Signals" / "30_Sessions").exists())
        self.assertTrue((root / "Signals" / "50_Review" / "review-tasks.md").exists())
        self.assertTrue((root / "Signals" / "60_Parking_Lot").exists())

        all_text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.md"))
        self.assertNotIn("OPENAI_API_KEY", all_text)
        self.assertNotIn("api_providers", all_text)
        self.assertGreater(result["files_written"], 0)


if __name__ == "__main__":
    unittest.main()
