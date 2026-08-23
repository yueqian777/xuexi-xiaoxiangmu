from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pages import course_center, dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READER_HTML = PROJECT_ROOT / "components" / "synced_reader" / "index.html"


class LearningExperienceV3UiTest(unittest.TestCase):
    def test_dashboard_counts_distinct_review_knowledge_points(self):
        tasks = [
            {"id": 1, "knowledge_id": 7, "topic": "ROC"},
            {"id": 2, "knowledge_id": 7, "topic": "ROC"},
            {"id": 3, "knowledge_id": 9, "topic": "卷积"},
        ]

        self.assertEqual(dashboard._today_review_knowledge_count(tasks), 2)

    def test_dashboard_source_is_a_today_learning_cockpit(self):
        source = (PROJECT_ROOT / "pages" / "dashboard.py").read_text(
            encoding="utf-8"
        )

        for label in [
            "今日学习驾驶舱",
            "今日学习",
            "继续：第",
            "今日复习",
            "个知识点",
            "待解决",
            "个插问",
            "课程概览",
            "学习中",
            "已完成",
            "归档",
        ]:
            self.assertIn(label, source)

    def test_dashboard_deck_only_context_is_not_claimed_as_saved_page(self):
        with (
            patch.object(
                dashboard,
                "get_active_context",
                return_value={"active": True, "deck_id": 11},
            ),
            patch.object(
                dashboard,
                "fetch_one",
                side_effect=[
                    {"id": 11, "title": "连续时间系统", "slide_count": 20},
                    None,
                ],
            ),
        ):
            location = dashboard._current_learning_location(7, {"id": 4})

        self.assertEqual(location["slide_number"], 1)
        self.assertFalse(location["has_saved_position"])

    def test_course_card_view_model_exposes_honest_progress_and_metrics(self):
        course = {
            "id": 4,
            "name": "信号与系统",
            "status": "active",
            "completed_at": None,
        }
        detail = {
            "decks": [
                {"id": 11, "title": "连续时间系统", "slide_count": 12},
                {"id": 12, "title": "Z 变换", "slide_count": 20},
            ],
            "learning_phases": [
                {
                    "phase_number": 1,
                    "started_at": "2026-03-05 09:00:00",
                    "ended_at": None,
                    "outcome": "",
                }
            ],
            "metrics": {
                "question_count": 6,
                "knowledge_count": 2,
                "core_knowledge": [{"topic": "卷积", "mastery": 80}],
                "weak_points": [{"topic": "ROC", "mastery": 60}],
            },
        }

        model = course_center._course_card_view_model(
            course,
            detail,
            {"active": True, "deck_id": 12, "slide_number": 5},
        )

        self.assertEqual(model["ppt_count"], 2)
        self.assertEqual(model["question_count"], 6)
        self.assertEqual(model["knowledge_count"], 2)
        self.assertEqual(model["mastery"], 70)
        self.assertEqual(model["progress_label"], "当前《Z 变换》第 5 / 20 页")
        self.assertIsNone(model["progress_percent"])
        self.assertEqual(model["cycle_label"], "2026春季学习")

    def test_historical_course_card_uses_frozen_ppt_count(self):
        course = {"id": 4, "name": "信号与系统", "status": "completed"}
        detail = {
            "course": course,
            "decks": [{"id": 12}, {"id": 13}, {"id": 14}],
            "summary": {
                "deck_count": 2,
                "question_count": 3,
                "knowledge_count": 1,
            },
            "metrics": {
                "deck_count": 2,
                "question_count": 3,
                "knowledge_count": 1,
            },
            "learning_phases": [],
        }

        model = course_center._course_card_view_model(
            course,
            detail,
            {"active": False},
        )

        self.assertEqual(model["ppt_count"], 2)

    def test_frozen_report_does_not_list_live_deck_details(self):
        historical_detail = {
            "summary": {"deck_count": 1},
            "decks": [{"id": 12, "title": "后来重新关联的资料"}],
        }
        live_detail = {
            "summary": None,
            "decks": [{"id": 13, "title": "当前资料"}],
        }

        self.assertEqual(course_center._report_deck_rows(historical_detail), [])
        self.assertEqual(
            course_center._report_deck_rows(live_detail),
            live_detail["decks"],
        )

    def test_legacy_course_summary_does_not_mix_in_live_resolved_count(self):
        detail = {
            "course": {
                "id": 4,
                "name": "信号与系统",
                "status": "completed",
                "completed_at": "2026-06-30 18:00:00",
            },
            "summary": {
                "started_at": "2026-03-01 08:00:00",
                "completed_at": "2026-06-30 18:00:00",
                "deck_count": 2,
                "slide_count": 64,
                "question_count": 8,
                "knowledge_count": 3,
                "core_knowledge": [{"topic": "卷积", "mastery": 85}],
                "weak_points": [{"topic": "ROC", "mastery": 55}],
                "future_review_advice": "优先复习 ROC。",
            },
            "metrics": {"resolved_question_count": 5},
            "decks": [],
            "learning_phases": [],
        }

        report = course_center._course_report_view_model(detail)

        self.assertEqual(report["learning_time"], "2026-03-01 至 2026-06-30")
        self.assertEqual(report["completed_content"], "2 份资料 · 64 页")
        self.assertIsNone(report["resolved_question_count"])
        self.assertEqual(report["question_count"], 8)
        self.assertEqual(report["knowledge_count"], 3)
        self.assertEqual(report["mastery"], 70)
        self.assertEqual(report["future_review_advice"], "优先复习 ROC。")

    def test_reactivated_legacy_report_does_not_mix_in_current_cycle_answers(self):
        detail = {
            "course": {"id": 4, "status": "active"},
            "summary": {
                "question_count": 2,
                "knowledge_count": 0,
                "core_knowledge": [],
                "weak_points": [],
            },
            "metrics": {
                "question_count": 5,
                "resolved_question_count": 4,
            },
        }

        report = course_center._course_report_view_model(detail)

        self.assertEqual(report["question_count"], 2)
        self.assertIsNone(report["resolved_question_count"])

    def test_archived_progress_uses_latest_cycle_outcome(self):
        progress = course_center._course_progress(
            {"status": "archived"},
            [],
            [
                {"phase_number": 1, "outcome": "completed"},
                {"phase_number": 2, "outcome": "archived"},
            ],
            {"active": False},
        )

        self.assertEqual(progress, ("课程已归档", None))

    def test_learning_cycles_get_stable_names_and_current_marker(self):
        phases = [
            {
                "id": 1,
                "phase_number": 1,
                "started_at": "2026-03-05 09:00:00",
                "ended_at": "2026-06-30 18:00:00",
                "outcome": "completed",
            },
            {
                "id": 2,
                "phase_number": 2,
                "started_at": "2027-01-08 09:00:00",
                "ended_at": None,
                "outcome": "",
            },
        ]

        models = course_center._learning_cycle_view_models(phases)

        self.assertEqual(models[0]["label"], "2026春季学习")
        self.assertEqual(models[1]["label"], "2027复习阶段")
        self.assertFalse(models[0]["is_current"])
        self.assertTrue(models[1]["is_current"])
        self.assertEqual(models[0]["phase_heading"], "阶段 1")
        self.assertEqual(models[1]["phase_heading"], "阶段 2")

    def test_learning_cycle_keeps_its_viewable_report_snapshot(self):
        snapshot = {
            "question_count": 4,
            "resolved_question_count": 3,
            "knowledge_count": 2,
            "core_knowledge": [],
            "weak_points": [],
        }
        models = course_center._learning_cycle_view_models(
            [
                {
                    "phase_number": 1,
                    "started_at": "2026-03-01",
                    "ended_at": "2026-06-30",
                    "outcome": "completed",
                    "course_summary": json.dumps(snapshot, ensure_ascii=False),
                }
            ]
        )

        self.assertEqual(models[0]["snapshot"], snapshot)
        self.assertIn(
            "查看本周期报告",
            (PROJECT_ROOT / "pages" / "course_center.py").read_text(
                encoding="utf-8"
            ),
        )

    def test_course_center_source_has_card_grid_report_and_cycle_flow(self):
        source = (PROJECT_ROOT / "pages" / "course_center.py").read_text(
            encoding="utf-8"
        )

        for label in [
            "_render_course_grid",
            "完成时间",
            "学习进度",
            "PPT",
            "问题",
            "知识卡",
            "掌握度",
            "课程学习报告",
            "学习时间",
            "完成内容",
            "知识体系",
            "解决问题数量",
            "薄弱点",
            "未来复习建议",
            "学习周期",
            "当前阶段",
            "开始新周期",
            "历史周期不会被覆盖",
        ]:
            self.assertIn(label, source)

    def test_synced_reader_has_one_accessible_three_tab_learning_sidebar(self):
        source = READER_HTML.read_text(encoding="utf-8")

        self.assertIn("学习侧栏", source)
        self.assertIn('role="tablist"', source)
        tabs = [
            source.index('data-learning-tab="understanding"'),
            source.index('data-learning-tab="deposition"'),
            source.index('data-learning-tab="review"'),
        ]
        self.assertEqual(tabs, sorted(tabs))
        for label in ["理解", "AI讲解", "当前问题", "沉淀", "插问", "知识卡", "复习", "掌握度", "复习计划"]:
            self.assertIn(label, source)
        self.assertNotIn('data-resize-handle="notes-chat"', source)
        self.assertNotRegex(
            source,
            r"@media \(max-width: 900px\)[\s\S]*?\.canvas-chat\s*\{\s*display:\s*none",
        )


if __name__ == "__main__":
    unittest.main()
