import unittest
from unittest.mock import patch

from repositories import ppt_repository


class PptRepositoryTest(unittest.TestCase):
    def test_add_slide_explanation_normalizes_ids_and_returns_insert_id(self):
        with patch.object(ppt_repository, "insert_and_get_id", return_value=77) as insert_and_get_id:
            result = ppt_repository.add_slide_explanation("4", "9", "模型", "讲解")

        self.assertEqual(result, 77)
        query, params = insert_and_get_id.call_args.args
        self.assertIn("INSERT INTO slide_explanations", query)
        self.assertEqual(params, (4, 9, "模型", "讲解"))

    def test_add_slide_question_normalizes_ids_and_returns_insert_id(self):
        with patch.object(ppt_repository, "insert_and_get_id", return_value=88) as insert_and_get_id:
            result = ppt_repository.add_slide_question("4", "9", "问题", "答案", "模型", quote_text="引用")

        self.assertEqual(result, 88)
        query, params = insert_and_get_id.call_args.args
        self.assertIn("INSERT INTO slide_questions", query)
        self.assertIn("quote_text", query)
        self.assertEqual(params, (4, 9, "问题", "引用", "答案", "模型"))

    def test_latest_explanations_by_slide_ids_returns_empty_for_no_ids(self):
        with patch.object(ppt_repository, "fetch_all") as fetch_all:
            self.assertEqual(ppt_repository.latest_explanations_by_slide_ids(4, []), {})

        fetch_all.assert_not_called()

    def test_latest_explanations_by_slide_ids_groups_by_slide_id(self):
        rows = [
            {"id": 11, "slide_id": 7, "model": "模型", "explanation": "讲解", "created_at": "today"},
        ]
        with patch.object(ppt_repository, "fetch_all", return_value=rows) as fetch_all:
            result = ppt_repository.latest_explanations_by_slide_ids("4", ["7"])

        self.assertEqual(result, {7: rows[0]})
        query, params = fetch_all.call_args.args
        self.assertIn("ROW_NUMBER()", query)
        self.assertEqual(params, (4, 7))

    def test_questions_by_slide_ids_returns_empty_lists_for_requested_slides(self):
        with patch.object(ppt_repository, "fetch_all", return_value=[]):
            result = ppt_repository.questions_by_slide_ids(4, [7, 8])

        self.assertEqual(result, {7: [], 8: []})

    def test_questions_by_slide_ids_groups_rows_in_repository(self):
        rows = [
            {
                "slide_id": 7,
                "question": "问题",
                "answer": "答案",
                "model": "模型",
                "category": "",
                "status": "未整理",
                "sort_order": 0,
                "created_at": "today",
            },
        ]
        with patch.object(ppt_repository, "fetch_all", return_value=rows) as fetch_all:
            result = ppt_repository.questions_by_slide_ids("4", ["7"])

        self.assertEqual(result, {7: rows})
        query, params = fetch_all.call_args.args
        self.assertIn("quote_text", query)
        self.assertIn("ORDER BY sort_order ASC, created_at ASC, id ASC", query)
        self.assertEqual(params, (4, 7))


if __name__ == "__main__":
    unittest.main()
