from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from pages import knowledge_cards
from services import course_service
from services.course_content_write_service import (
    convert_parking_question_to_card,
    create_knowledge_card_record,
    create_study_session_record,
    update_knowledge_card_record,
    update_study_session_record,
)


class CourseUiWriteTransactionTest(unittest.TestCase):
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

    def test_cross_user_session_course_is_not_inherited_by_manual_card(self) -> None:
        foreign_course = course_service.create_course(999, "外部课程")
        session_id = db.insert_and_get_id(
            """
            INSERT INTO study_sessions (
                user_id, date, subject, title, main_question, course_id
            )
            VALUES (?, '2026-08-23', '本地课程', '学习记录', '核心问题', ?)
            """,
            (self.user_id, foreign_course["id"]),
        )

        sessions = knowledge_cards._list_source_sessions(
            self.user_id,
            include_archived=True,
        )
        self.assertEqual(sessions[0]["id"], session_id)
        self.assertIsNone(sessions[0]["owned_course_id"])

        knowledge_id = create_knowledge_card_record(
            self.user_id,
            subject="本地课程",
            topic="本地知识",
            core_question="为什么？",
            one_sentence="因为。",
            logic_or_formula="",
            application="",
            mastery=60,
            need_review=False,
            source_session_id=session_id,
        )

        card = db.fetch_one(
            """
            SELECT kc.course_id, c.user_id AS course_user_id, c.name AS course_name
            FROM knowledge_cards kc
            JOIN courses c ON c.id = kc.course_id
            WHERE kc.id = ?
            """,
            (knowledge_id,),
        )
        self.assertEqual(card["course_user_id"], self.user_id)
        self.assertEqual(card["course_name"], "本地课程")
        self.assertNotEqual(card["course_id"], foreign_course["id"])

    def test_study_session_flow_rolls_back_course_session_card_and_reviews(self) -> None:
        with patch(
            "services.course_content_write_service.ensure_initial_review_tasks",
            side_effect=RuntimeError("review write failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "review write failed"):
                create_study_session_record(
                    self.user_id,
                    session_date="2026-08-23",
                    subject="事务课程",
                    chapter="第一章",
                    title="事务学习",
                    main_question="是否原子？",
                    mastered_content="",
                    blockers="",
                    wrong_questions="",
                    summary="",
                    mastery=60,
                    need_review=True,
                    is_key=False,
                    create_card=True,
                )

        self._assert_learning_counts(courses=0, sessions=0, cards=0, reviews=0)

    def test_manual_card_flow_rolls_back_course_card_and_reviews(self) -> None:
        with patch(
            "services.course_content_write_service.ensure_initial_review_tasks",
            side_effect=RuntimeError("review write failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "review write failed"):
                create_knowledge_card_record(
                    self.user_id,
                    subject="卡片事务课程",
                    topic="事务知识",
                    core_question="是否原子？",
                    one_sentence="必须同事务。",
                    logic_or_formula="",
                    application="",
                    mastery=50,
                    need_review=True,
                )

        self._assert_learning_counts(courses=0, sessions=0, cards=0, reviews=0)

    def test_parking_conversion_rolls_back_and_successful_retry_is_idempotent(self) -> None:
        parking_id = db.insert_and_get_id(
            """
            INSERT INTO parking_lot (user_id, subject, question, source)
            VALUES (?, '停车事务课', '为什么要原子转换？', '测试')
            """,
            (self.user_id,),
        )
        kwargs = {
            "topic": "原子转换",
            "one_sentence": "避免重复知识卡。",
            "logic_or_formula": "",
            "application": "",
            "mastery": 50,
            "need_review": True,
        }

        with patch(
            "services.course_content_write_service.ensure_initial_review_tasks",
            side_effect=RuntimeError("review write failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "review write failed"):
                convert_parking_question_to_card(
                    self.user_id,
                    parking_id,
                    **kwargs,
                )

        self._assert_learning_counts(courses=0, sessions=0, cards=0, reviews=0)
        self.assertEqual(
            db.fetch_one("SELECT status FROM parking_lot WHERE id = ?", (parking_id,))["status"],
            "未解决",
        )

        first_id = convert_parking_question_to_card(self.user_id, parking_id, **kwargs)
        second_id = convert_parking_question_to_card(self.user_id, parking_id, **kwargs)

        self.assertIsInstance(first_id, int)
        self.assertIsNone(second_id)
        self._assert_learning_counts(courses=1, sessions=0, cards=1, reviews=4)
        self.assertEqual(
            db.fetch_one("SELECT status FROM parking_lot WHERE id = ?", (parking_id,))["status"],
            "已转知识点",
        )

    def test_session_and_card_create_and_edit_reject_blank_subject_in_chinese(self) -> None:
        with self.assertRaisesRegex(ValueError, "^科目不能为空。$"):
            create_study_session_record(
                self.user_id,
                session_date="2026-08-23",
                subject="   ",
                chapter="",
                title="空科目学习",
                main_question="为什么？",
                mastered_content="",
                blockers="",
                wrong_questions="",
                summary="",
                mastery=60,
                need_review=False,
                is_key=False,
                create_card=False,
            )
        with self.assertRaisesRegex(ValueError, "^科目不能为空。$"):
            create_knowledge_card_record(
                self.user_id,
                subject="\t",
                topic="空科目卡片",
                core_question="为什么？",
                one_sentence="因为。",
                logic_or_formula="",
                application="",
                mastery=60,
                need_review=False,
            )

        session_id, _ = create_study_session_record(
            self.user_id,
            session_date="2026-08-23",
            subject="有效课程",
            chapter="",
            title="有效学习",
            main_question="为什么？",
            mastered_content="",
            blockers="",
            wrong_questions="",
            summary="",
            mastery=60,
            need_review=False,
            is_key=False,
            create_card=False,
        )
        knowledge_id = create_knowledge_card_record(
            self.user_id,
            subject="有效课程",
            topic="有效知识",
            core_question="为什么？",
            one_sentence="因为。",
            logic_or_formula="",
            application="",
            mastery=60,
            need_review=False,
        )

        with self.assertRaisesRegex(ValueError, "^科目不能为空。$"):
            update_study_session_record(
                self.user_id,
                session_id,
                session_date="2026-08-23",
                subject="",
                chapter="",
                title="有效学习",
                main_question="为什么？",
                mastered_content="",
                blockers="",
                wrong_questions="",
                summary="",
                mastery=60,
                need_review=False,
                is_key=False,
            )
        with self.assertRaisesRegex(ValueError, "^科目不能为空。$"):
            update_knowledge_card_record(
                self.user_id,
                knowledge_id,
                subject=" ",
                topic="有效知识",
                core_question="为什么？",
                one_sentence="因为。",
                logic_or_formula="",
                application="",
                mastery=60,
                need_review=False,
            )

        self.assertEqual(
            db.fetch_one("SELECT subject FROM study_sessions WHERE id = ?", (session_id,))["subject"],
            "有效课程",
        )
        self.assertEqual(
            db.fetch_one("SELECT subject FROM knowledge_cards WHERE id = ?", (knowledge_id,))["subject"],
            "有效课程",
        )

    def _assert_learning_counts(
        self,
        *,
        courses: int,
        sessions: int,
        cards: int,
        reviews: int,
    ) -> None:
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS n FROM courses")["n"], courses)
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS n FROM study_sessions")["n"], sessions)
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS n FROM knowledge_cards")["n"], cards)
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS n FROM review_tasks")["n"], reviews)


if __name__ == "__main__":
    unittest.main()
