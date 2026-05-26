import unittest

from pages import ppt_tutor


class PptStudyAssetBatchTest(unittest.TestCase):
    def test_build_study_asset_batches_splits_by_sections(self):
        slides = [
            {"id": 1, "slide_number": 1, "section_index": 1, "title": "A", "slide_text": "内容 A"},
            {"id": 2, "slide_number": 2, "section_index": 2, "title": "B", "slide_text": "内容 B"},
        ]
        sections = [
            {"section_index": 1, "title": "第一块", "start_slide": 1, "end_slide": 1},
            {"section_index": 2, "title": "第二块", "start_slide": 2, "end_slide": 2},
        ]

        batches = ppt_tutor._build_study_asset_batches(
            slides,
            sections=sections,
            max_chars=8000,
            include_ai_explanation=False,
            split_by_sections=True,
            fallback_range_label="全部目录块",
        )

        self.assertEqual(len(batches), 2)
        self.assertIn("第一块", batches[0]["range_label"])
        self.assertIn("第二块", batches[1]["range_label"])
        self.assertEqual([batch["used_pages"] for batch in batches], [1, 1])

    def test_merge_study_asset_batches_keeps_cards_from_each_batch(self):
        batch_results = [
            {
                "batch": {"range_label": "目录块 1", "used_pages": 2, "truncated": False},
                "assets": {
                    "study_session": {
                        "summary": "第一块总结",
                        "mastered_content": "会 A",
                        "blockers": "卡 A",
                        "wrong_questions": "问 A",
                        "mastery": 60,
                    },
                    "knowledge_cards": [{"subject": "数学", "topic": "A", "one_sentence": "A"}],
                },
            },
            {
                "batch": {"range_label": "目录块 2", "used_pages": 2, "truncated": False},
                "assets": {
                    "study_session": {
                        "summary": "第二块总结",
                        "mastered_content": "会 B",
                        "blockers": "卡 B",
                        "wrong_questions": "问 B",
                        "mastery": 55,
                    },
                    "knowledge_cards": [{"subject": "数学", "topic": "B", "one_sentence": "B"}],
                },
            },
        ]

        merged = ppt_tutor._merge_study_asset_batches(
            batch_results,
            deck={"title": "讲义", "subject": "数学"},
            range_label="全部目录块",
        )

        self.assertEqual(len(merged["knowledge_cards"]), 2)
        self.assertEqual(merged["study_session"]["mastery"], 55)
        self.assertIn("目录块 1：第一块总结", merged["study_session"]["summary"])
        self.assertIn("目录块 2：第二块总结", merged["study_session"]["summary"])

    def test_coverage_report_marks_missing_cards(self):
        batches = [
            {"range_label": "目录块 1", "used_pages": 2, "truncated": False},
            {"range_label": "目录块 2", "used_pages": 3, "truncated": True},
        ]
        batch_results = [
            {
                "batch": batches[0],
                "assets": {"knowledge_cards": [{"topic": "A"}]},
            }
        ]

        report = ppt_tutor._build_study_asset_coverage_report(batch_results, batches)

        self.assertEqual(report[0]["状态"], "已覆盖")
        self.assertEqual(report[1]["状态"], "需补充")
        self.assertEqual(report[1]["截断"], "是")


if __name__ == "__main__":
    unittest.main()
