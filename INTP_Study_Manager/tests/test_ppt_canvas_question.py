from contextlib import nullcontext
import unittest
from unittest.mock import patch

from pages import ppt_tutor


class PptCanvasQuestionTest(unittest.TestCase):
    def test_display_branch_question_extracts_typed_question_from_legacy_prompt(self):
        legacy_question = "\n".join(
            [
                "我选中了第 9 页的一段内容，想围绕这段话插问。",
                "",
                "引用内容：",
                "周期信号",
                "",
                "前文上下文：",
                "如果 f(t) 是周期为 T 的",
                "",
                "后文上下文：",
                "直接相关",
                "",
                "我的问题：",
                "为什么这里强调周期信号？",
            ]
        )

        self.assertEqual(
            ppt_tutor._display_branch_question(legacy_question),
            "为什么这里强调周期信号？",
        )

    def test_canvas_question_saves_typed_question_while_prompt_keeps_quote_context(self):
        deck = {"id": 3, "title": "信号课件", "subject": "信号与系统"}
        slide = {"id": 9, "slide_number": 2, "title": "周期信号", "slide_text": "本页正文"}
        payload = {
            "action": "canvas_question",
            "deckId": 3,
            "slideNumber": 2,
            "token": "tok-1",
            "question": "为什么这里强调周期信号？",
            "quote": {
                "slideTitle": "周期信号",
                "selectedText": "周期信号",
                "contextBefore": "如果 f(t) 是周期为 T 的",
                "contextAfter": "直接相关",
            },
        }
        prompt_inputs = {}

        def build_prompt(_deck, _slide, _latest, question, *, context=None):
            prompt_inputs["question"] = question
            return "model prompt"

        with (
            patch.object(ppt_tutor.st, "session_state", {}),
            patch.object(ppt_tutor.st, "spinner", return_value=nullcontext()),
            patch.object(ppt_tutor.st, "rerun") as rerun,
            patch.object(ppt_tutor, "build_slide_context_map", return_value={2: {"same_section": []}}),
            patch.object(ppt_tutor, "_build_branch_prompt", side_effect=build_prompt),
            patch.object(ppt_tutor, "generate_text", return_value="回答内容") as generate_text,
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 11})()),
            patch.object(ppt_tutor, "_active_model_label", return_value="测试模型"),
            patch.object(ppt_tutor, "add_slide_question") as add_slide_question,
        ):
            ppt_tutor._handle_synced_reader_action(
                deck,
                [slide],
                {9: {"explanation": "主线讲解"}},
                payload,
                [],
            )

        self.assertIn("引用内容", prompt_inputs["question"])
        self.assertIn("周期信号", prompt_inputs["question"])
        self.assertTrue(prompt_inputs["question"].endswith("为什么这里强调周期信号？"))
        generate_text.assert_called_once()
        add_slide_question.assert_called_once_with(11, 9, "为什么这里强调周期信号？", "回答内容", "测试模型")
        rerun.assert_called_once()


if __name__ == "__main__":
    unittest.main()
