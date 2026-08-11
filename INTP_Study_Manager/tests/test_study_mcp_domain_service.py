from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from repositories import ppt_repository
from services import study_mcp_domain_service as domain


class StudyMcpDomainServiceTest(unittest.TestCase):
    def setUp(self) -> None:
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
        self.other_user_id = 12
        self.deck_id, self.slide_ids = self._create_deck(self.user_id, "Signals", 4)
        self.other_deck_id, self.other_slide_ids = self._create_deck(self.other_user_id, "Private", 2)
        db.execute(
            """
            INSERT INTO ppt_sections (
                user_id, deck_id, section_index, title, topic, core_question,
                summary, key_terms_json, prerequisite_concepts_json, start_slide, end_slide
            )
            VALUES (?, ?, 1, 'ROC block', 'ROC', 'Why ROC?', 'Section summary',
                    '[\"ROC\", \"unit circle\"]', '[\"complex numbers\"]', 1, 4)
            """,
            (self.user_id, self.deck_id),
        )

    def _create_deck(self, user_id: int, title: str, slide_count: int) -> tuple[int, list[int]]:
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, filename, title, subject, file_path, slide_count
            )
            VALUES (?, ?, ?, 'DSP', ?, ?)
            """,
            (user_id, f"{title}.pdf", title, f"C:/private/{title}.pdf", slide_count),
        )
        slide_ids: list[int] = []
        for slide_number in range(1, slide_count + 1):
            slide_ids.append(
                db.insert_and_get_id(
                    """
                    INSERT INTO ppt_slides (
                        user_id, deck_id, slide_number, title, slide_text, image_path,
                        section_index, page_type, one_sentence_summary, slide_role, key_points
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, '公式页', ?, '核心页', ?)
                    """,
                    (
                        user_id,
                        deck_id,
                        slide_number,
                        f"Slide {slide_number}",
                        f"Slide text {slide_number}",
                        f"C:/private/slide-{slide_number}.png",
                        f"Summary {slide_number}",
                        f"Point {slide_number}",
                    ),
                )
            )
        return deck_id, slide_ids

    def _active_context(self, slide_number: int = 2) -> dict:
        return {
            "active": True,
            "user_id": self.user_id,
            "subject": "DSP",
            "deck_id": self.deck_id,
            "deck_title": "Signals",
            "slide_id": self.slide_ids[slide_number - 1],
            "slide_number": slide_number,
            "selection": None,
            "updated_at": "2026-08-11 12:00:00",
        }

    def assert_no_local_paths(self, payload) -> None:
        if isinstance(payload, dict):
            self.assertNotIn("file_path", payload)
            self.assertNotIn("image_path", payload)
            for value in payload.values():
                self.assert_no_local_paths(value)
        elif isinstance(payload, list):
            for value in payload:
                self.assert_no_local_paths(value)

    def test_get_current_slide_returns_latest_explanation_section_and_bounded_neighbors(self):
        slide_id = self.slide_ids[1]
        ppt_repository.add_slide_explanation(self.user_id, slide_id, "old", "Old explanation")
        latest_id = ppt_repository.add_slide_explanation(self.user_id, slide_id, "new", "Latest explanation")

        with patch.object(domain, "get_active_context", return_value=self._active_context()):
            result = domain.get_current_slide(
                self.user_id,
                include_neighbor_context=True,
                neighbor_radius=2,
            )

        self.assertEqual(result["slide_id"], slide_id)
        self.assertEqual(result["deck"]["deck_id"], self.deck_id)
        self.assertEqual(result["section"]["section_index"], 1)
        self.assertEqual(result["latest_explanation"]["explanation_id"], latest_id)
        self.assertEqual(result["latest_explanation"]["explanation"], "Latest explanation")
        self.assertEqual([row["slide_number"] for row in result["neighbors"]], [1, 3, 4])
        self.assertTrue(result["deck_fingerprint"].startswith("sha256:"))
        self.assert_no_local_paths(result)

    def test_get_current_slide_rejects_neighbor_radius_above_two_before_context_lookup(self):
        with patch.object(domain, "get_active_context") as get_context:
            with self.assertRaises(domain.StudyDomainError) as caught:
                domain.get_current_slide(
                    self.user_id,
                    include_neighbor_context=True,
                    neighbor_radius=3,
                )

        self.assertEqual(caught.exception.code, "neighbor_radius_exceeded")
        get_context.assert_not_called()

    def test_get_current_slide_reports_missing_active_slide(self):
        with patch.object(domain, "get_active_context", return_value={"active": False}):
            with self.assertRaises(domain.StudyDomainError) as caught:
                domain.get_current_slide(self.user_id)

        self.assertEqual(caught.exception.code, "active_context_missing")

    def test_stale_active_context_and_error_payload_are_structured(self):
        stale = self._active_context()
        stale["slide_number"] = None

        with patch.object(domain, "get_active_context", return_value=stale):
            with self.assertRaises(domain.StudyDomainError) as caught:
                domain.get_current_slide(self.user_id)

        self.assertEqual(caught.exception.code, "active_context_stale")
        payload = domain.StudyDomainError(
            "example_error",
            "safe message",
            details={"maximum": 2},
        ).to_dict()
        self.assertEqual(
            payload,
            {
                "success": False,
                "error": {
                    "code": "example_error",
                    "message": "safe message",
                    "details": {"maximum": 2},
                },
            },
        )

    def test_read_slide_range_returns_whitelisted_deck_sections_and_slides(self):
        result = domain.read_slide_range(self.user_id, self.deck_id, 2, 4)

        self.assertEqual(result["deck"]["deck_id"], self.deck_id)
        self.assertEqual([row["slide_number"] for row in result["slides"]], [2, 3, 4])
        self.assertEqual([row["section_index"] for row in result["sections"]], [1])
        self.assertTrue(result["deck_fingerprint"].startswith("sha256:"))
        self.assert_no_local_paths(result)

    def test_read_slide_range_rejects_more_than_25_pages_before_database_access(self):
        with patch.object(domain, "_get_owned_deck") as get_deck:
            with self.assertRaises(domain.StudyDomainError) as caught:
                domain.read_slide_range(self.user_id, self.deck_id, 1, 26)

        self.assertEqual(caught.exception.code, "slide_range_too_large")
        get_deck.assert_not_called()

    def test_read_slide_range_rejects_reversed_or_missing_ranges(self):
        with self.assertRaises(domain.StudyDomainError) as reversed_range:
            domain.read_slide_range(self.user_id, self.deck_id, 3, 2)
        self.assertEqual(reversed_range.exception.code, "invalid_slide_range")

        with self.assertRaises(domain.StudyDomainError) as missing_range:
            domain.read_slide_range(self.user_id, self.deck_id, 4, 5)
        self.assertEqual(missing_range.exception.code, "resource_not_found")

        with self.assertRaises(domain.StudyDomainError) as fractional_id:
            domain.read_slide_range(self.user_id, float(self.deck_id) + 0.2, 1, 2)
        self.assertEqual(fractional_id.exception.code, "invalid_argument")

    def test_read_slide_range_rejects_cross_user_deck(self):
        with self.assertRaises(domain.StudyDomainError) as caught:
            domain.read_slide_range(self.user_id, self.other_deck_id, 1, 2)

        self.assertEqual(caught.exception.code, "resource_not_found")

    def test_question_tree_preserves_root_child_and_grandchild(self):
        slide_id = self.slide_ids[0]
        root = ppt_repository.create_slide_question_tree_node(self.user_id, slide_id, "root", "a", "m")
        child = ppt_repository.create_slide_question_tree_node(
            self.user_id, slide_id, "child", "a", "m", parent_question_id=root
        )
        grandchild = ppt_repository.create_slide_question_tree_node(
            self.user_id, slide_id, "grandchild", "a", "m", parent_question_id=child
        )

        result = domain.get_question_tree(self.user_id, slide_id)

        self.assertEqual(result["questions"][0]["id"], root)
        self.assertEqual(result["questions"][0]["children"][0]["id"], child)
        node = result["questions"][0]["children"][0]["children"][0]
        self.assertEqual(node["id"], grandchild)
        self.assertEqual(node["root_question_id"], root)
        self.assertEqual(node["parent_question_id"], child)
        self.assertEqual(node["depth"], 2)
        self.assertNotIn("user_id", result["questions"][0])

    def test_add_slide_question_reuses_repository_tree_and_rejects_cross_slide_parent(self):
        slide_id = self.slide_ids[0]
        root = domain.add_slide_question(self.user_id, slide_id, "root", "root answer")
        child = domain.add_slide_question(
            self.user_id,
            slide_id,
            "child",
            "child answer",
            parent_question_id=root["question_id"],
            quote_text="root answer fragment",
        )

        child_row = db.fetch_one("SELECT * FROM slide_questions WHERE id = ?", (child["question_id"],))
        self.assertEqual(child_row["parent_question_id"], root["question_id"])
        self.assertEqual(child_row["root_question_id"], root["question_id"])
        self.assertEqual(child_row["depth"], 1)
        self.assertEqual(child_row["model"], "ChatGPT MCP")
        self.assertEqual(child_row["quote_source"], "question_answer")

        with self.assertRaises(domain.StudyDomainError) as caught:
            domain.add_slide_question(
                self.user_id,
                self.slide_ids[1],
                "wrong slide child",
                "answer",
                parent_question_id=root["question_id"],
            )
        self.assertEqual(caught.exception.code, "invalid_parent_question")

    def test_add_slide_question_rejects_cross_user_slide_before_repository_write(self):
        with self.assertRaises(domain.StudyDomainError) as caught:
            domain.add_slide_question(
                self.user_id,
                self.other_slide_ids[0],
                "question",
                "answer",
            )

        self.assertEqual(caught.exception.code, "resource_not_found")
        count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_questions WHERE user_id = ?",
            (self.user_id,),
        )
        self.assertEqual(count["count"], 0)

    def test_add_slide_question_validates_empty_long_and_invalid_unicode_text(self):
        cases = [
            ("", "answer", "invalid_argument"),
            ("q", "a" * (domain.MAX_QUESTION_ANSWER_CHARS + 1), "input_too_long"),
            ("\ud800", "answer", "invalid_unicode"),
        ]
        for question, answer, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(domain.StudyDomainError) as caught:
                    domain.add_slide_question(
                        self.user_id,
                        self.slide_ids[0],
                        question,
                        answer,
                    )
                self.assertEqual(caught.exception.code, expected_code)

    def test_get_and_search_knowledge_are_user_scoped_and_bounded(self):
        owned_id = self._create_knowledge(self.user_id, "ROC", "Unit circle and convergence")
        self._create_knowledge(self.other_user_id, "Private ROC", "private")

        card = domain.get_knowledge_card(self.user_id, owned_id)
        results = domain.search_knowledge(self.user_id, "convergence", subject="DSP", limit=5)

        self.assertEqual(card["id"], owned_id)
        self.assertEqual([row["id"] for row in results], [owned_id])
        self.assertNotIn("user_id", card)
        with self.assertRaises(domain.StudyDomainError) as missing:
            domain.get_knowledge_card(self.other_user_id, owned_id)
        self.assertEqual(missing.exception.code, "resource_not_found")
        with self.assertRaises(domain.StudyDomainError) as too_many:
            domain.search_knowledge(self.user_id, "ROC", limit=51)
        self.assertEqual(too_many.exception.code, "search_limit_exceeded")

    def test_knowledge_search_rejects_oversized_query_and_subject_before_database_read(self):
        with patch.object(domain.knowledge_card_service, "search_knowledge_cards") as search:
            with self.assertRaises(domain.StudyDomainError) as long_query:
                domain.search_knowledge(
                    self.user_id,
                    "q" * (domain.MAX_KNOWLEDGE_QUERY_CHARS + 1),
                )
            with self.assertRaises(domain.StudyDomainError) as long_subject:
                domain.search_knowledge(
                    self.user_id,
                    "ROC",
                    subject="s" * (domain.MAX_KNOWLEDGE_SUBJECT_CHARS + 1),
                )

        self.assertEqual(long_query.exception.code, "input_too_long")
        self.assertEqual(long_subject.exception.code, "input_too_long")
        search.assert_not_called()
        with self.assertRaises(domain.StudyDomainError) as empty_query:
            domain.search_knowledge(self.user_id, "   ")
        self.assertEqual(empty_query.exception.code, "invalid_argument")

    def test_knowledge_repository_search_treats_wildcards_as_literal_and_validates_bounds(self):
        percent_id = self._create_knowledge(self.user_id, "100% ROC", "literal percent")
        self._create_knowledge(self.user_id, "Plain ROC", "no percent")

        results = domain.knowledge_card_service.search_knowledge_cards(
            self.user_id,
            "100%",
            limit=5,
        )

        self.assertEqual([row["id"] for row in results], [percent_id])
        with self.assertRaises(ValueError):
            domain.knowledge_card_service.search_knowledge_cards(self.user_id, "")
        with self.assertRaises(ValueError):
            domain.knowledge_card_service.search_knowledge_cards(
                self.user_id,
                "ROC",
                limit=domain.knowledge_card_service.MAX_SEARCH_LIMIT + 1,
            )
        with self.assertRaises(ValueError):
            domain.knowledge_card_service.get_knowledge_card(True, percent_id)
        with self.assertRaises(ValueError):
            domain.knowledge_card_service.get_knowledge_card(-1, percent_id)
        with self.assertRaises(ValueError):
            domain.knowledge_card_service.get_knowledge_card("not-a-user", percent_id)
        with self.assertRaises(ValueError):
            domain.knowledge_card_service.get_knowledge_card(self.user_id, percent_id + 0.2)
        with self.assertRaises(ValueError):
            domain.knowledge_card_service.search_knowledge_cards(
                self.user_id,
                "ROC",
                limit=0,
            )

    def _create_knowledge(self, user_id: int, topic: str, one_sentence: str) -> int:
        return db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, core_question, one_sentence,
                logic_or_formula, application, mastery, need_review
            )
            VALUES (?, 'DSP', ?, 'Core?', ?, 'Formula', 'Application', 60, 1)
            """,
            (user_id, topic, one_sentence),
        )

    def test_convert_mark_understood_and_create_review_reuse_existing_services(self):
        slide_id = self.slide_ids[0]
        question = domain.add_slide_question(self.user_id, slide_id, "What is ROC?", "ROC answer")

        first = domain.convert_question_to_knowledge(self.user_id, question["question_id"])
        second = domain.convert_question_to_knowledge(self.user_id, question["question_id"])
        understood = domain.mark_question_understood(self.user_id, question["question_id"])
        review = domain.create_review_for_question(self.user_id, question["question_id"])

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["knowledge_id"], second["knowledge_id"])
        self.assertTrue(understood["understood"])
        self.assertEqual(review["knowledge_id"], first["knowledge_id"])
        tasks = db.fetch_one(
            "SELECT COUNT(*) AS count FROM review_tasks WHERE user_id = ? AND knowledge_id = ?",
            (self.user_id, first["knowledge_id"]),
        )
        self.assertEqual(tasks["count"], 4)

    def test_get_today_reviews_and_submit_review_result_are_structured(self):
        knowledge_id = self._create_knowledge(self.user_id, "Sampling", "Sampling theorem")
        task_id = db.insert_and_get_id(
            """
            INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
            VALUES (?, ?, '2020-01-01', '第 1 天复习')
            """,
            (self.user_id, knowledge_id),
        )

        today = domain.get_today_reviews(self.user_id)
        submitted = domain.submit_review_result(self.user_id, task_id, "基本掌握")

        self.assertEqual(today[0]["review_task_id"], task_id)
        self.assertEqual(today[0]["knowledge_id"], knowledge_id)
        self.assertEqual(today[0]["mastery"], 60)
        self.assertEqual(submitted["review_task_id"], task_id)
        self.assertEqual(submitted["result"], "基本掌握")
        self.assertGreater(submitted["mastery_after"], submitted["mastery_before"])

        with self.assertRaises(domain.StudyDomainError) as already_done:
            domain.submit_review_result(self.user_id, task_id, "基本掌握")
        self.assertEqual(already_done.exception.code, "review_task_not_pending")

    def test_submit_review_result_maps_invalid_result_to_domain_error(self):
        knowledge_id = self._create_knowledge(self.user_id, "DFT", "Discrete Fourier transform")
        task_id = db.insert_and_get_id(
            """
            INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
            VALUES (?, ?, '2020-01-01', '第 1 天复习')
            """,
            (self.user_id, knowledge_id),
        )

        with self.assertRaises(domain.StudyDomainError) as caught:
            domain.submit_review_result(self.user_id, task_id, "invented")

        self.assertEqual(caught.exception.code, "invalid_review_result")
        row = db.fetch_one("SELECT status FROM review_tasks WHERE id = ?", (task_id,))
        self.assertEqual(row["status"], "待复习")


if __name__ == "__main__":
    unittest.main()
