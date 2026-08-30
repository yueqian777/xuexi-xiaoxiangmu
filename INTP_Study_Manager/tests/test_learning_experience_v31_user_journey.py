from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import app
import db
from services import course_service
from services.active_learning_context_service import get_active_context
from services.ppt_reader_state import (
    LAST_READER_DECK_STATE_KEY,
    reader_active_slide_state_key,
)
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LearningExperienceV31UserJourneyTest(unittest.TestCase):
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

        self.signal = self._seed_course(
            "信号与系统",
            question_count=2,
            mastery_values=[85],
        )
        course_service.complete_course(0, self.signal["course_id"])
        self.digital = self._seed_course(
            "数字电路",
            question_count=1,
            mastery_values=[40, 60],
        )
        course_service.archive_course(0, self.digital["course_id"])

    def _seed_course(
        self,
        name: str,
        *,
        question_count: int,
        mastery_values: list[int],
    ) -> dict[str, int]:
        course = course_service.create_course(0, name)
        course_id = int(course["id"])
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, course_id, filename, title, subject, file_path, slide_count
            )
            VALUES (0, ?, ?, ?, ?, ?, 3)
            """,
            (
                course_id,
                f"{name}.pdf",
                f"{name}课件",
                name,
                f"{name}.pdf",
            ),
        )
        slide_ids = [
            db.insert_and_get_id(
                """
                INSERT INTO ppt_slides (
                    user_id, deck_id, slide_number, title, slide_text
                )
                VALUES (0, ?, ?, ?, ?)
                """,
                (deck_id, number, f"第 {number} 页", f"正文 {number}"),
            )
            for number in range(1, 4)
        ]
        for index in range(question_count):
            db.insert_and_get_id(
                """
                INSERT INTO slide_questions (
                    user_id, slide_id, question, answer, model
                )
                VALUES (0, ?, ?, '测试回答', 'test-model')
                """,
                (slide_ids[index % len(slide_ids)], f"{name}插问 {index + 1}"),
            )
        for index, mastery in enumerate(mastery_values, start=1):
            db.insert_and_get_id(
                """
                INSERT INTO knowledge_cards (
                    user_id, course_id, subject, topic, one_sentence,
                    mastery, need_review
                )
                VALUES (0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    course_id,
                    name,
                    f"{name}知识 {index}",
                    f"{name}核心结论 {index}",
                    mastery,
                    int(mastery < 70),
                ),
            )
        return {"course_id": course_id, "deck_id": int(deck_id)}

    def _open_course_center(self) -> AppTest:
        page = AppTest.from_file(
            PROJECT_ROOT / "app.py",
            default_timeout=20,
        ).run()
        page.sidebar.radio[1].set_value("course_center")
        page.run()
        self.assertEqual(
            len(page.exception),
            0,
            [str(item.value) for item in page.exception],
        )
        return page

    def _button(self, page: AppTest, key: str):
        return next(
            item
            for item in page.button
            if getattr(item, "key", None) == key
        )

    def _assert_report_entry(
        self,
        course: dict[str, int],
        *,
        name: str,
        status_label: str,
    ) -> None:
        page = self._open_course_center()
        self._button(page, f"course_report_{course['course_id']}").click()
        page.run()
        page.run()

        self.assertEqual(
            len(page.exception),
            0,
            [str(item.value) for item in page.exception],
        )
        self.assertIn("课程学习报告", [item.value for item in page.title])
        self.assertIn(name, [item.value for item in page.title])
        self.assertIn(("状态", status_label), [(item.label, item.value) for item in page.metric])
        self.assertIn("学习周期", [item.value for item in page.subheader])
        self.assertIn("查看本周期报告", [item.label for item in page.expander])

    def _reactivate_and_continue(
        self,
        course: dict[str, int],
        detail_before: dict,
    ) -> None:
        course_id = course["course_id"]
        deck_id = course["deck_id"]
        page = self._open_course_center()

        self._button(page, f"course_reactivate_{course_id}").click()
        page.run()
        page.run()

        detail_after = course_service.get_course_detail(0, course_id)
        self.assertIsNotNone(detail_after)
        assert detail_after is not None
        self.assertEqual(detail_after["course"]["status"], "active")
        self.assertEqual(len(detail_before["learning_phases"]), 1)
        self.assertEqual(len(detail_after["learning_phases"]), 2)
        self.assertEqual(
            detail_after["learning_phases"][0],
            detail_before["learning_phases"][0],
        )
        self.assertEqual(detail_after["summary"], detail_before["summary"])
        self.assertEqual(
            self._button(page, f"course_open_{course_id}").label,
            "继续学习",
        )

        self._button(page, f"course_open_{course_id}").click()
        page.run()
        page.run()

        self.assertEqual(
            len(page.exception),
            0,
            [str(item.value) for item in page.exception],
        )
        self.assertEqual(page.session_state[app.SELECTED_SECTION_STATE_KEY], "materials")
        self.assertEqual(page.session_state[app.SELECTED_PAGE_STATE_KEY], "ppt_tutor")
        self.assertEqual(page.session_state[LAST_READER_DECK_STATE_KEY], deck_id)
        self.assertEqual(
            page.session_state[reader_active_slide_state_key(deck_id)],
            1,
        )
        active_context = get_active_context(0)
        self.assertEqual(active_context["deck_id"], deck_id)
        self.assertEqual(active_context["slide_number"], 1)

    def test_completed_and_archived_courses_restart_without_losing_history(self) -> None:
        page = self._open_course_center()
        markdown = [str(item.value) for item in page.markdown]
        self.assertIn("### 信号与系统", markdown)
        self.assertIn("**已完成**", markdown)
        self.assertIn("### 数字电路", markdown)
        self.assertIn("**已归档**", markdown)

        metrics = Counter((item.label, item.value) for item in page.metric)
        self.assertEqual(metrics[("PPT 数量", "1")], 2)
        self.assertEqual(metrics[("问题数量", "2")], 1)
        self.assertEqual(metrics[("问题数量", "1")], 1)
        self.assertEqual(metrics[("知识卡数量", "1")], 1)
        self.assertEqual(metrics[("知识卡数量", "2")], 1)
        self.assertEqual(metrics[("掌握度", "85%")], 1)
        self.assertEqual(metrics[("掌握度", "50%")], 1)

        for course in (self.signal, self.digital):
            course_id = course["course_id"]
            self.assertEqual(
                self._button(page, f"course_open_{course_id}").label,
                "查看历史",
            )
            self.assertEqual(
                self._button(page, f"course_report_{course_id}").label,
                "查看总结",
            )
            self.assertEqual(
                self._button(page, f"course_reactivate_{course_id}").label,
                "开始新周期",
            )

        self._assert_report_entry(
            self.signal,
            name="信号与系统",
            status_label="已完成",
        )
        self._assert_report_entry(
            self.digital,
            name="数字电路",
            status_label="已归档",
        )

        signal_before = course_service.get_course_detail(
            0,
            self.signal["course_id"],
        )
        digital_before = course_service.get_course_detail(
            0,
            self.digital["course_id"],
        )
        self.assertIsNotNone(signal_before)
        self.assertIsNotNone(digital_before)
        assert signal_before is not None
        assert digital_before is not None

        self._reactivate_and_continue(self.signal, signal_before)
        self._reactivate_and_continue(self.digital, digital_before)


if __name__ == "__main__":
    unittest.main()
