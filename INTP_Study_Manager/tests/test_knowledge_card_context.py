from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from pages import knowledge_cards as knowledge_cards_page
from services.course_service import archive_course, create_course
from services.knowledge_card_service import (
    knowledge_card_preview_markdown,
    list_knowledge_cards_with_context,
)


class KnowledgeCardContextTest(unittest.TestCase):
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
        self.user_id = 71

    def test_context_is_user_scoped_and_archived_cards_require_opt_in(self) -> None:
        active = create_course(self.user_id, "信号与系统")
        archived = create_course(self.user_id, "工程伦理")
        foreign = create_course(99, "其他用户课程")
        archive_course(self.user_id, archived["id"])

        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, course_id, filename, title, subject, file_path, slide_count
            )
            VALUES (?, ?, 'fir.pdf', '第八章 FIR 数字滤波器', '信号与系统', 'fir.pdf', 1)
            """,
            (self.user_id, active["id"]),
        )
        slide_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text)
            VALUES (?, ?, 31, '线性相位', '正文')
            """,
            (self.user_id, deck_id),
        )
        question_id = db.insert_and_get_id(
            """
            INSERT INTO slide_questions (user_id, slide_id, question, answer, model)
            VALUES (?, ?, '为什么对称冲激响应保证线性相位？', '因为相位项线性。', 'test')
            """,
            (self.user_id, slide_id),
        )
        active_card_id = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, course_id, subject, topic, one_sentence,
                source_deck_id, source_slide_id, source_question_id
            )
            VALUES (?, ?, '信号与系统', '线性相位 FIR 条件', '对称性约束相位', ?, ?, ?)
            """,
            (self.user_id, active["id"], deck_id, slide_id, question_id),
        )
        db.insert_and_get_id(
            """
            INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage, status)
            VALUES (?, ?, '2026-09-03', '第 7 天复习', '待复习')
            """,
            (self.user_id, active_card_id),
        )
        session_id = db.insert_and_get_id(
            """
            INSERT INTO study_sessions (
                user_id, course_id, date, subject, title, main_question
            )
            VALUES (?, ?, '2026-08-23', '信号与系统', 'FIR 阅读', '窗函数如何影响频谱？')
            """,
            (self.user_id, active["id"]),
        )
        for slide_number in (31, 32):
            db.insert_and_get_id(
                """
                INSERT INTO ppt_study_asset_pages (
                    user_id, deck_id, slide_number, session_id, range_label
                )
                VALUES (?, ?, ?, ?, '第 31-32 页')
                """,
                (self.user_id, deck_id, slide_number, session_id),
            )
        session_card_id = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, course_id, subject, topic, one_sentence, source_session_id
            )
            VALUES (?, ?, '信号与系统', '窗函数选择', '按阻带指标选择窗函数', ?)
            """,
            (self.user_id, active["id"], session_id),
        )
        db.insert_and_get_id(
            """
            INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage, status)
            VALUES (?, ?, '2026-09-01', '第 3 天复习', '待复习')
            """,
            (self.user_id, active_card_id),
        )
        archived_card_id = self._insert_simple_card(
            self.user_id,
            archived["id"],
            "工程责任",
        )
        self._insert_simple_card(99, foreign["id"], "不应泄露")

        current_cards = list_knowledge_cards_with_context(self.user_id)
        all_cards = list_knowledge_cards_with_context(
            self.user_id,
            include_archived=True,
        )

        self.assertEqual(
            {card["id"] for card in current_cards},
            {active_card_id, session_card_id},
        )
        self.assertEqual(
            {card["id"] for card in all_cards},
            {active_card_id, session_card_id, archived_card_id},
        )
        active_card = next(card for card in current_cards if card["id"] == active_card_id)
        self.assertEqual(active_card["course_name"], "信号与系统")
        self.assertEqual(active_card["course_status"], "active")
        self.assertEqual(active_card["source_deck_title"], "第八章 FIR 数字滤波器")
        self.assertEqual(active_card["source_slide_number"], 31)
        self.assertEqual(active_card["source_question"], "为什么对称冲激响应保证线性相位？")
        self.assertEqual(active_card["next_review_date"], "2026-09-01")
        session_card = next(card for card in current_cards if card["id"] == session_card_id)
        self.assertIsNone(session_card["source_slide_number"])
        self.assertEqual(session_card["source_page_range"], "第 31-32 页")
        rendered = knowledge_card_preview_markdown(session_card)
        self.assertIn("页码范围", rendered)
        self.assertIn("第 31-32 页", rendered)

    def test_archived_linked_cards_require_the_same_explicit_opt_in(self) -> None:
        active = create_course(self.user_id, "当前知识")
        archived = create_course(self.user_id, "历史知识")
        active_card_id = self._insert_simple_card(
            self.user_id,
            active["id"],
            "当前卡",
        )
        archived_card_id = self._insert_simple_card(
            self.user_id,
            archived["id"],
            "历史卡",
        )
        db.insert_and_get_id(
            """
            INSERT INTO knowledge_links (
                user_id, source_knowledge_id, target_knowledge_id, relation_type
            ) VALUES (?, ?, ?, '前置知识')
            """,
            (self.user_id, active_card_id, archived_card_id),
        )
        archive_course(self.user_id, archived["id"])

        current_links = knowledge_cards_page._knowledge_links_for_card(
            self.user_id,
            active_card_id,
            direction="outgoing",
            include_archived=False,
        )
        all_links = knowledge_cards_page._knowledge_links_for_card(
            self.user_id,
            active_card_id,
            direction="outgoing",
            include_archived=True,
        )

        self.assertEqual(current_links, [])
        self.assertEqual([row["linked_id"] for row in all_links], [archived_card_id])

    @staticmethod
    def _insert_simple_card(user_id: int, course_id: int, topic: str) -> int:
        return db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, course_id, subject, topic, one_sentence
            )
            VALUES (?, ?, '测试课程', ?, '测试结论')
            """,
            (user_id, course_id, topic),
        )


if __name__ == "__main__":
    unittest.main()
