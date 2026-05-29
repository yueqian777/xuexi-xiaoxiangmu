from __future__ import annotations

import unittest

from services.knowledge_card_service import (
    knowledge_card_preview_markdown,
    mastery_level,
)


class KnowledgeCardServiceTest(unittest.TestCase):
    def test_preview_markdown_keeps_latex_and_learning_sections(self):
        card = {
            "subject": "信号与系统",
            "topic": "Z 变换 ROC",
            "core_question": "ROC 为什么能决定系统因果性和稳定性？",
            "one_sentence": "ROC 是让 Z 变换级数收敛的 z 平面区域。",
            "logic_or_formula": "$$X(z)=\\sum_{n=-\\infty}^{\\infty}x[n]z^{-n}$$\n\n- 因果序列 ROC 在最外极点之外。",
            "application": "看到极点分布，先判断 ROC，再判断因果性与稳定性。",
            "mastery": 62,
        }

        rendered = knowledge_card_preview_markdown(card)

        self.assertIn("### Z 变换 ROC", rendered)
        self.assertIn("**核心问题**", rendered)
        self.assertIn("**一句话抓手**", rendered)
        self.assertIn("**公式 / 推导**", rendered)
        self.assertIn("**应用 / 快速定位**", rendered)
        self.assertIn("$$X(z)=\\sum_{n=-\\infty}^{\\infty}x[n]z^{-n}$$", rendered)
        self.assertIn("巩固中", rendered)

    def test_preview_markdown_uses_placeholders_for_sparse_cards(self):
        rendered = knowledge_card_preview_markdown({"topic": "未完成卡片", "mastery": 25})

        self.assertIn("### 未完成卡片", rendered)
        self.assertIn("待补充核心问题", rendered)
        self.assertIn("待补充一句话解释", rendered)
        self.assertIn("薄弱", rendered)

    def test_mastery_level_describes_review_priority(self):
        self.assertEqual(mastery_level(92)["label"], "迁移熟练")
        self.assertEqual(mastery_level(76)["label"], "基本掌握")
        self.assertEqual(mastery_level(58)["label"], "巩固中")
        self.assertEqual(mastery_level(33)["label"], "薄弱")


if __name__ == "__main__":
    unittest.main()
