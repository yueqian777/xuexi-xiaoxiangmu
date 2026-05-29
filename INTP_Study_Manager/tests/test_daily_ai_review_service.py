from __future__ import annotations

import unittest
from pathlib import Path

from services.daily_ai_review_service import (
    _normalize_plan_payload,
    daily_review_question_markdown,
)


class DailyAiReviewServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            {
                "knowledge_id": 1,
                "subject": "信号与系统",
                "topic": "Z 变换 ROC",
                "core_question": "ROC 为什么能决定系统因果性和稳定性？",
                "one_sentence": "ROC 是让 Z 变换级数收敛的 z 平面区域。",
                "logic_or_formula": "因果序列 ROC 在最外极点之外；稳定要求单位圆在 ROC 内。",
                "application": "看到极点分布，先判断 ROC，再判断因果性与稳定性。",
                "mastery": 62,
                "review_stage": "第 3 天复习",
                "last_cause": "条件漏看",
            }
        ]

    def test_normalize_plan_replaces_formula_writing_demands(self):
        payload = {
            "main_line": "检查 ROC 的条件边界。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "公式默写题",
                    "review_focus": "公式记忆",
                    "question": "请用 LaTeX 写出 Z 变换公式，并推导完整公式。",
                    "answer_format": "写公式和 LaTeX。",
                    "expected_points": ["写出公式", "说明 ROC"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertEqual(question["question_type"], "快速定位题")
        self.assertIn("核心问题", question["question"])
        self.assertIn("2-4 句", question["answer_format"])
        combined = "\n".join(
            [
                question["question"],
                question["answer_format"],
                *question["expected_points"],
            ]
        )
        self.assertNotIn("LaTeX", combined)
        self.assertNotIn("写公式", combined)
        self.assertNotIn("写出公式", combined)

    def test_normalize_plan_keeps_concrete_numeric_calculation(self):
        payload = {
            "main_line": "用一个小计算检查 ROC 判断。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "数据计算题",
                    "review_focus": "用具体极点判断稳定性",
                    "question": "已知系统极点半径为 0.5 和 2，若 ROC 为 0.5 < |z| < 2，判断单位圆是否在 ROC 内，并说明系统是否稳定。",
                    "answer_format": "写判断结果 + 1 句理由。",
                    "given_data": ["极点半径：0.5、2", "ROC：0.5 < |z| < 2", "单位圆半径：1"],
                    "expected_points": ["1 在 0.5 和 2 之间", "单位圆在 ROC 内", "系统稳定"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertEqual(question["question_type"], "数据计算题")
        self.assertEqual(question["given_data"], ["极点半径：0.5、2", "ROC：0.5 < |z| < 2", "单位圆半径：1"])
        self.assertIn("写判断结果", question["answer_format"])
        self.assertIn("单位圆", question["question"])

    def test_data_calculation_without_concrete_data_is_downgraded(self):
        payload = {
            "main_line": "检查计算题是否给数据。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "数据计算题",
                    "question": "计算这个系统是否稳定。",
                    "answer_format": "写计算结果。",
                    "expected_points": ["判断稳定性"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertNotEqual(question["question_type"], "数据计算题")
        self.assertEqual(question["given_data"], [])
        self.assertIn("核心问题", question["question"])

    def test_data_calculation_ignores_ordinal_numbers_without_given_data(self):
        payload = {
            "main_line": "章节号不是可计算数据。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "数据计算题",
                    "question": "第 2 章例 1 中，这个系统是否稳定？",
                    "answer_format": "写判断结果。",
                    "expected_points": ["判断稳定性"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertNotEqual(question["question_type"], "数据计算题")
        self.assertEqual(question["given_data"], [])
        self.assertIn("核心问题", question["question"])

    def test_data_calculation_with_placeholder_given_data_is_downgraded(self):
        payload = {
            "main_line": "占位数据不能算具体数据。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "数据计算题",
                    "question": "计算这个系统是否稳定。",
                    "answer_format": "写判断结果。",
                    "given_data": ["例 1 的相关参数见题干"],
                    "expected_points": ["判断稳定性"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertNotEqual(question["question_type"], "数据计算题")
        self.assertEqual(question["given_data"], [])
        self.assertIn("核心问题", question["question"])

    def test_data_calculation_with_mixed_placeholder_given_data_is_downgraded(self):
        payload = {
            "main_line": "混入占位数据时不能保留为计算题。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "数据计算题",
                    "question": "根据给定数据判断系统是否稳定。",
                    "answer_format": "写判断结果。",
                    "given_data": ["相关参数见题干", "单位圆半径：1"],
                    "expected_points": ["判断稳定性"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertNotEqual(question["question_type"], "数据计算题")
        self.assertEqual(question["given_data"], [])
        self.assertIn("核心问题", question["question"])

    def test_data_calculation_with_reference_only_given_data_is_downgraded(self):
        payload = {
            "main_line": "例题编号不是可计算数据。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "数据计算题",
                    "question": "判断这个系统是否稳定。",
                    "answer_format": "写判断结果。",
                    "given_data": ["例 1、题 2"],
                    "expected_points": ["判断稳定性"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertNotEqual(question["question_type"], "数据计算题")
        self.assertEqual(question["given_data"], [])
        self.assertIn("核心问题", question["question"])

    def test_data_calculation_with_ranged_question_reference_is_downgraded(self):
        payload = {
            "main_line": "题号范围不是可计算数据。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "数据计算题",
                    "question": "判断这个系统是否稳定。",
                    "answer_format": "写判断结果。",
                    "given_data": ["第 1、2 题"],
                    "expected_points": ["判断稳定性"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertNotEqual(question["question_type"], "数据计算题")
        self.assertEqual(question["given_data"], [])
        self.assertIn("核心问题", question["question"])

    def test_data_calculation_with_punctuated_question_reference_is_downgraded(self):
        payload = {
            "main_line": "带冒号的题号范围也不是可计算数据。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": 1,
                    "topic": "Z 变换 ROC",
                    "question_type": "数据计算题",
                    "question": "判断这个系统是否稳定。",
                    "answer_format": "写判断结果。",
                    "given_data": ["第 1、2 题："],
                    "expected_points": ["判断稳定性"],
                }
            ],
        }

        plan = _normalize_plan_payload(payload, self.candidates, 1)
        question = plan["questions"][0]

        self.assertNotEqual(question["question_type"], "数据计算题")
        self.assertEqual(question["given_data"], [])
        self.assertIn("核心问题", question["question"])

    def test_question_markdown_is_card_like_and_does_not_leak_answer_key(self):
        question = {
            "question_id": "q1",
            "knowledge_id": 1,
            "topic": "Z 变换 ROC",
            "question_type": "数据计算题",
            "review_focus": "判断条件边界",
            "question": "已知 ROC 为 0.5 < |z| < 2，判断单位圆是否在 ROC 内。",
            "answer_format": "写判断结果 + 1 句理由。",
            "given_data": ["ROC：0.5 < |z| < 2", "单位圆半径：1"],
            "expected_points": ["单位圆在 ROC 内"],
        }

        rendered = daily_review_question_markdown(question, 1)

        self.assertIn("### 1. Z 变换 ROC", rendered)
        self.assertIn("**考点**", rendered)
        self.assertIn("**题目**", rendered)
        self.assertIn("**给定数据**", rendered)
        self.assertIn("**作答方式**", rendered)
        self.assertNotIn("expected_points", rendered)
        self.assertNotIn("单位圆在 ROC 内", rendered)

    def test_plan_prompt_forbids_latex_writing_and_requires_concrete_data(self):
        prompt = Path("prompts/daily_ai_review_plan.md").read_text(encoding="utf-8")

        self.assertIn("不要要求用户写公式", prompt)
        self.assertIn("不要要求用户写 LaTeX", prompt)
        self.assertIn("数据计算题必须给出具体数据", prompt)

    def test_dashboard_user_visible_copy_hides_latex_wording(self):
        dashboard_source = Path("pages/dashboard.py").read_text(encoding="utf-8")

        self.assertIn("无需特殊公式格式", dashboard_source)
        self.assertNotIn("不需要写 LaTeX", dashboard_source)
        self.assertNotIn("不用 LaTeX", dashboard_source)


if __name__ == "__main__":
    unittest.main()
