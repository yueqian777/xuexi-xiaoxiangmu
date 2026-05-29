import unittest
from contextlib import nullcontext
from unittest.mock import patch

from pages import ppt_management


class PptManagementTest(unittest.TestCase):
    def test_fetch_questions_marks_root_and_child_question_kind(self):
        rows = [
            {
                "id": 1,
                "question": "根问题",
                "quote_text": "",
                "answer": "根回答",
                "model": "模型",
                "category": "",
                "status": "未整理",
                "sort_order": 0,
                "slide_number": 2,
                "slide_title": "标题",
                "parent_question_id": None,
                "root_question_id": 1,
                "question_kind": "root",
                "thread_root_id": 1,
            },
            {
                "id": 2,
                "question": "子问题",
                "quote_text": "引用",
                "answer": "子回答",
                "model": "模型",
                "category": "",
                "status": "未整理",
                "sort_order": 1,
                "slide_number": 2,
                "slide_title": "标题",
                "parent_question_id": 1,
                "root_question_id": 1,
                "question_kind": "child",
                "thread_root_id": 1,
            },
        ]
        with patch.object(ppt_management, "fetch_all", return_value=rows) as fetch_all:
            result = ppt_management._fetch_questions(11, 3)

        query, params = fetch_all.call_args.args
        self.assertIn("question_kind", query)
        self.assertIn("thread_root_id", query)
        self.assertEqual(params, (11, 3))
        self.assertEqual(result[0]["question_kind"], "root")
        self.assertEqual(result[1]["question_kind"], "child")
        self.assertEqual(result[1]["question_preview"], "子问题")

    def test_question_row_style_distinguishes_root_and_child_without_level_label(self):
        root_style = ppt_management._question_row_style({"question_kind": "root", "id": 1})
        child_style = ppt_management._question_row_style({"question_kind": "child", "id": 2})

        self.assertTrue(all("background-color" in item for item in root_style))
        self.assertTrue(all("background-color" in item for item in child_style))
        self.assertNotEqual(root_style[0], child_style[0])

    def test_delete_question_uses_recursive_thread_delete(self):
        questions = [
            {
                "id": 1,
                "slide_number": 2,
                "question": "根问题",
                "quote_text": "",
                "answer": "根回答",
            }
        ]
        with (
            patch.object(ppt_management.st, "subheader"),
            patch.object(ppt_management.st, "selectbox", return_value=1),
            patch.object(ppt_management.st, "expander", return_value=nullcontext()),
            patch.object(ppt_management.st, "markdown"),
            patch.object(ppt_management.st, "text_input", return_value="DELETE"),
            patch.object(ppt_management.st, "button", return_value=True),
            patch.object(ppt_management.st, "success"),
            patch.object(ppt_management.st, "rerun") as rerun,
            patch.object(ppt_management, "delete_slide_question_thread", return_value=3) as delete_thread,
            patch.object(ppt_management, "execute") as execute,
        ):
            ppt_management._render_question_detail_and_delete(11, questions, [])

        delete_thread.assert_called_once_with(11, 1)
        execute.assert_not_called()
        rerun.assert_called_once()


if __name__ == "__main__":
    unittest.main()
