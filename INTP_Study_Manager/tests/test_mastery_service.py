from __future__ import annotations

import unittest

from services.mastery_service import apply_review_result, clamp_mastery, review_result_profile


class MasteryServiceTest(unittest.TestCase):
    def test_review_result_updates_are_quality_weighted(self):
        self.assertEqual(apply_review_result(60, "完全掌握"), 69)
        self.assertEqual(apply_review_result(60, "基本掌握"), 64)
        self.assertEqual(apply_review_result(60, "仍然模糊"), 53)
        self.assertEqual(apply_review_result(60, "完全不会"), 45)

    def test_review_result_clamps_at_bounds(self):
        self.assertEqual(apply_review_result(98, "完全掌握"), 100)
        self.assertEqual(apply_review_result(5, "完全不会"), 0)
        self.assertEqual(apply_review_result(42, "未知结果"), 42)
        self.assertEqual(clamp_mastery(-10), 0)
        self.assertEqual(clamp_mastery(120), 100)

    def test_review_result_profile_explains_observed_recall_quality(self):
        profile = review_result_profile("完全掌握")

        self.assertEqual(profile["quality"], 5)
        self.assertIn("闭卷", profile["evidence"])


if __name__ == "__main__":
    unittest.main()
