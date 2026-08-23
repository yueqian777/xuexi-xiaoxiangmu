import unittest
from pathlib import Path
from unittest.mock import patch

import app
from pages import course_center, ppt_tutor
from services.knowledge_card_service import knowledge_card_preview_markdown


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LearningWorkflowV2UiTest(unittest.TestCase):
    def test_app_registers_course_center_in_today_flow(self):
        today_entries = [
            entry for entry in app.NAV_ENTRIES if entry.section_id == "today"
        ]

        self.assertEqual(
            [(entry.id, entry.label) for entry in today_entries],
            [("dashboard", "学习驾驶舱"), ("course_center", "课程中心")],
        )

    def test_dashboard_is_action_oriented_learning_cockpit(self):
        source = (PROJECT_ROOT / "pages" / "dashboard.py").read_text(
            encoding="utf-8"
        )

        for label in [
            "学习驾驶舱",
            "今日学习",
            "当前课程",
            "今日任务",
            "课程状态",
            "继续学习",
        ]:
            self.assertIn(label, source)
        self.assertIn("get_dashboard_snapshot", source)

    def test_question_payload_keeps_learning_state_and_source_links(self):
        rows = {
            9: [
                {
                    "id": 12,
                    "question": "为什么需要窗函数？",
                    "quote_text": "",
                    "answer": "用于控制截断带来的频谱效应。",
                    "model": "test-model",
                    "category": "概念卡点",
                    "status": "未整理",
                    "knowledge_id": 31,
                    "converted_to_knowledge": 1,
                    "understood": 0,
                    "need_review": 1,
                    "root_question_id": 12,
                    "parent_question_id": None,
                    "depth": 0,
                    "quote_source": "slide",
                    "quote_source_question_id": None,
                    "sort_order": 0,
                    "created_at": "2026-08-23 10:00:00",
                }
            ]
        }

        with patch.object(ppt_tutor, "questions_by_slide_ids", return_value=rows):
            payload = ppt_tutor._questions_by_slide_ids([9])[9][0]

        self.assertEqual(payload["learningStatus"], "已转知识卡")
        self.assertEqual(payload["knowledgeId"], 31)
        self.assertTrue(payload["convertedToKnowledge"])
        self.assertFalse(payload["understood"])
        self.assertTrue(payload["needReview"])

    def test_reader_payload_contains_current_page_cards_and_review_state(self):
        slides = [
            {
                "id": 9,
                "slide_number": 31,
                "title": "FIR 窗函数",
                "image_path": "",
            }
        ]
        learning_records = {
            9: {
                "knowledge_cards": [
                    {
                        "id": 31,
                        "topic": "线性相位 FIR 条件",
                        "mastery": 60,
                        "next_review_date": "2026-09-01",
                    }
                ],
                "review_status": {
                    "pending_count": 1,
                    "next_review_date": "2026-09-01",
                },
            }
        }

        payload = ppt_tutor._build_reader_payload(
            slides,
            {},
            {9: []},
            learning_record_by_slide_id=learning_records,
        )[0]

        self.assertEqual(payload["knowledgeCards"][0]["topic"], "线性相位 FIR 条件")
        self.assertEqual(payload["reviewStatus"]["pending_count"], 1)

    def test_synced_reader_right_column_is_unified_learning_record(self):
        source = (
            PROJECT_ROOT / "components" / "synced_reader" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn('class="canvas-chat-title">学习记录', source)
        for label in ["问题树", "知识卡", "复习"]:
            self.assertIn(label, source)

    def test_knowledge_card_preview_shows_provenance_mastery_and_next_review(self):
        markdown = knowledge_card_preview_markdown(
            {
                "subject": "信号与系统",
                "course_name": "信号与系统",
                "topic": "线性相位 FIR 条件",
                "core_question": "为什么对称冲激响应保证线性相位？",
                "one_sentence": "对称性让相位项保持线性。",
                "logic_or_formula": "h[n] = h[N-1-n]",
                "application": "FIR 滤波器设计",
                "mastery": 60,
                "source_deck_title": "第八章 FIR 数字滤波器",
                "source_slide_number": 31,
                "source_question": "为什么对称冲激响应保证线性相位？",
                "next_review_date": "2026-09-01",
            }
        )

        for text in [
            "来源",
            "第八章 FIR 数字滤波器",
            "第 31 页",
            "来源插问",
            "★★★☆☆",
            "2026-09-01",
        ]:
            self.assertIn(text, markdown)

    def test_course_center_exposes_full_lifecycle_actions(self):
        path = PROJECT_ROOT / "pages" / "course_center.py"
        self.assertTrue(path.exists(), "课程中心页面尚未创建")
        source = path.read_text(encoding="utf-8") if path.exists() else ""

        for label in [
            "当前学习",
            "历史课程",
            "结束课程",
            "归档",
            "重新激活",
            "查看总结",
            "学习时间",
            "核心知识体系",
        ]:
            self.assertIn(label, source)

    def test_course_center_continue_uses_the_saved_position_for_that_course(self):
        decks = [{"id": 4}, {"id": 9}]
        with patch.object(
            course_center,
            "get_active_context",
            return_value={"active": True, "deck_id": 9, "slide_number": 31},
        ):
            target = course_center._course_learning_target(7, decks)

        self.assertEqual(target, {"deck_id": 9, "slide_number": 31})

    def test_review_page_hides_archived_courses_until_explicitly_requested(self):
        source = (PROJECT_ROOT / "pages" / "reviews.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("包含已归档课程", source)
        self.assertGreaterEqual(source.count("include_archived=include_archived"), 2)


if __name__ == "__main__":
    unittest.main()
