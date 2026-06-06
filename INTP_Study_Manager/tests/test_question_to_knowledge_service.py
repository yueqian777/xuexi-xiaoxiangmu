import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from repositories import ppt_repository
from services import question_to_knowledge_service


class QuestionToKnowledgeServiceTest(unittest.TestCase):
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
        self.user_id = 11
        self.deck_id, self.slide_id = self._create_deck_and_slide()

    def _create_deck_and_slide(self):
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, 'signals.pdf', 'Z Transform', 'Signals', 'signals.pdf', 1)
            """,
            (self.user_id,),
        )
        slide_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text)
            VALUES (?, ?, 1, 'ROC', 'ROC and unit circle')
            """,
            (self.user_id, deck_id),
        )
        return deck_id, slide_id

    def _create_question(self, text, *, parent_question_id=None, answer=None):
        return ppt_repository.create_slide_question_tree_node(
            self.user_id,
            self.slide_id,
            text,
            answer or f"{text} answer first paragraph.\n\nMore detail.",
            "model",
            parent_question_id=parent_question_id,
        )

    def test_root_child_and_grandchild_questions_convert_to_source_cards(self):
        root = self._create_question("Why must ROC include unit circle?")
        child = self._create_question("Why does unit circle mean frequency?", parent_question_id=root)
        grandchild = self._create_question("Where does z=e^jw come from?", parent_question_id=child)

        created_ids = [
            question_to_knowledge_service.convert_question_to_knowledge(self.user_id, question_id)["knowledge_id"]
            for question_id in (root, child, grandchild)
        ]

        cards = db.fetch_all(
            """
            SELECT id, subject, topic, core_question, one_sentence, source_deck_id, source_slide_id, source_question_id
            FROM knowledge_cards
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (self.user_id,),
        )
        self.assertEqual([card["id"] for card in cards], created_ids)
        self.assertEqual([card["source_question_id"] for card in cards], [root, child, grandchild])
        self.assertTrue(all(card["subject"] == "Signals" for card in cards))
        self.assertTrue(all(card["source_deck_id"] == self.deck_id for card in cards))
        self.assertTrue(all(card["source_slide_id"] == self.slide_id for card in cards))

        question_rows = db.fetch_all(
            "SELECT id, converted_to_knowledge, knowledge_id FROM slide_questions ORDER BY id ASC"
        )
        self.assertEqual([row["converted_to_knowledge"] for row in question_rows], [1, 1, 1])
        self.assertEqual([row["knowledge_id"] for row in question_rows], created_ids)

    def test_conversion_with_review_tasks_is_idempotent(self):
        question_id = self._create_question("What is ROC?")

        first = question_to_knowledge_service.convert_question_to_knowledge(
            self.user_id,
            question_id,
            overrides={"topic": "ROC", "mastery": 55},
            create_review_tasks=True,
        )
        second = question_to_knowledge_service.convert_question_to_knowledge(
            self.user_id,
            question_id,
            create_review_tasks=True,
        )

        self.assertEqual(first["knowledge_id"], second["knowledge_id"])
        self.assertFalse(second["created"])
        self.assertEqual(
            db.fetch_one("SELECT COUNT(*) AS count FROM knowledge_cards WHERE user_id = ?", (self.user_id,))["count"],
            1,
        )
        review_tasks = db.fetch_all(
            "SELECT review_date, review_stage FROM review_tasks WHERE user_id = ? AND knowledge_id = ? ORDER BY review_date",
            (self.user_id, first["knowledge_id"]),
        )
        self.assertEqual(len(review_tasks), 4)
        self.assertEqual(
            db.fetch_one("SELECT need_review FROM slide_questions WHERE id = ?", (question_id,))["need_review"],
            1,
        )

    def test_deleted_linked_card_allows_reconversion_without_crashing(self):
        question_id = self._create_question("Can this be rebuilt?")
        first = question_to_knowledge_service.convert_question_to_knowledge(self.user_id, question_id)
        db.execute("DELETE FROM knowledge_cards WHERE id = ? AND user_id = ?", (first["knowledge_id"], self.user_id))

        second = question_to_knowledge_service.convert_question_to_knowledge(self.user_id, question_id)

        self.assertNotEqual(first["knowledge_id"], second["knowledge_id"])
        self.assertTrue(second["created"])
        row = db.fetch_one("SELECT knowledge_id, converted_to_knowledge FROM slide_questions WHERE id = ?", (question_id,))
        self.assertEqual(row["knowledge_id"], second["knowledge_id"])
        self.assertEqual(row["converted_to_knowledge"], 1)

    def test_missing_slide_or_deck_returns_clear_fallback(self):
        with db.managed_connection() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            cursor = conn.execute(
                """
                INSERT INTO slide_questions (user_id, slide_id, question, answer, model)
                VALUES (?, 99999, 'orphan question', 'orphan answer', 'model')
                """,
                (self.user_id,),
            )
            question_id = int(cursor.lastrowid)

        result = question_to_knowledge_service.convert_question_to_knowledge(self.user_id, question_id)

        self.assertTrue(result["created"])
        card = db.fetch_one("SELECT * FROM knowledge_cards WHERE id = ?", (result["knowledge_id"],))
        self.assertEqual(card["subject"], "Uncategorized")
        self.assertIsNone(card["source_deck_id"])
        self.assertIsNone(card["source_slide_id"])

    def test_mark_question_understood_only_sets_understood_flag(self):
        question_id = self._create_question("Understood?")

        changed = question_to_knowledge_service.mark_question_understood(self.user_id, question_id)

        self.assertTrue(changed)
        row = db.fetch_one("SELECT understood, status, knowledge_id FROM slide_questions WHERE id = ?", (question_id,))
        self.assertEqual(row["understood"], 1)
        self.assertEqual(row["status"], "understood")
        self.assertIsNone(row["knowledge_id"])


if __name__ == "__main__":
    unittest.main()
