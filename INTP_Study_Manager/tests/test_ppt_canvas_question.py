from contextlib import nullcontext
import unittest
from unittest.mock import patch

from pages import ppt_tutor


class PptCanvasQuestionTest(unittest.TestCase):
    def test_display_branch_question_parts_extract_legacy_prompt_question_and_quote(self):
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

        parts = ppt_tutor._branch_question_display_parts(legacy_question)

        self.assertEqual(
            parts["question"],
            "为什么这里强调周期信号？",
        )
        self.assertEqual(parts["quoteText"], "周期信号")

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
        add_slide_question.assert_called_once_with(
            11,
            9,
            "为什么这里强调周期信号？",
            "回答内容",
            "测试模型",
            quote_text="周期信号",
            parent_question_id=None,
            quote_source="slide",
            quote_source_question_id=None,
        )
        rerun.assert_called_once()

    def test_canvas_child_question_saves_parent_and_quote_source(self):
        deck = {"id": 3, "title": "信号课件", "subject": "信号与系统"}
        slide = {"id": 9, "slide_number": 2, "title": "周期信号", "slide_text": "本页正文"}
        payload = {
            "action": "canvas_question",
            "deckId": 3,
            "slideNumber": 2,
            "token": "tok-child",
            "question": "这句回答里的稳定性是什么意思？",
            "parentQuestionId": 12,
            "quote": {
                "sourceKind": "question_answer",
                "questionId": 12,
                "selectedText": "稳定性",
                "contextBefore": "用于判断系统",
                "contextAfter": "。",
            },
        }

        with (
            patch.object(ppt_tutor.st, "session_state", {}),
            patch.object(ppt_tutor.st, "spinner", return_value=nullcontext()),
            patch.object(ppt_tutor.st, "rerun"),
            patch.object(ppt_tutor, "build_slide_context_map", return_value={2: {"same_section": []}}),
            patch.object(ppt_tutor, "_build_branch_prompt", return_value="model prompt"),
            patch.object(ppt_tutor, "generate_text", return_value="子回答"),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 11})()),
            patch.object(ppt_tutor, "_active_model_label", return_value="测试模型"),
            patch.object(ppt_tutor, "add_slide_question") as add_slide_question,
        ):
            ppt_tutor._handle_synced_reader_action(deck, [slide], {9: {"explanation": "主线讲解"}}, payload, [])

        add_slide_question.assert_called_once_with(
            11,
            9,
            "这句回答里的稳定性是什么意思？",
            "子回答",
            "测试模型",
            quote_text="稳定性",
            parent_question_id=12,
            quote_source="question_answer",
            quote_source_question_id=12,
        )

    def test_canvas_answer_highlight_save_updates_question_answer_without_model_call(self):
        deck = {"id": 3, "title": "信号课件", "subject": "信号与系统"}
        slide = {"id": 9, "slide_number": 2, "title": "周期信号", "slide_text": "本页正文"}
        payload = {
            "action": "save_question_answer_edit",
            "deckId": 3,
            "slideNumber": 2,
            "token": "tok-answer-edit",
            "questionId": 12,
            "answer": "这里 ==稳定性== 指系统输出有界。",
        }

        with (
            patch.object(ppt_tutor.st, "session_state", {}),
            patch.object(ppt_tutor.st, "toast"),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 11})()),
            patch.object(ppt_tutor, "generate_text") as generate_text,
            patch.object(ppt_tutor, "update_slide_question_answer") as update_answer,
        ):
            ppt_tutor._handle_synced_reader_action(deck, [slide], {}, payload, [])

        generate_text.assert_not_called()
        update_answer.assert_called_once_with(11, 12, "这里 ==稳定性== 指系统输出有界。")

    def test_canvas_merge_question_thread_does_not_call_model(self):
        deck = {"id": 3, "title": "信号课件", "subject": "信号与系统"}
        slide = {"id": 9, "slide_number": 2, "title": "周期信号", "slide_text": "本页正文"}
        payload = {
            "action": "merge_question_thread",
            "deckId": 3,
            "slideNumber": 2,
            "token": "tok-merge",
            "questionId": 12,
        }

        with (
            patch.object(ppt_tutor.st, "session_state", {}),
            patch.object(ppt_tutor.st, "rerun") as rerun,
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 11})()),
            patch.object(ppt_tutor, "generate_text") as generate_text,
            patch.object(ppt_tutor, "flatten_question_subtree") as flatten,
        ):
            ppt_tutor._handle_synced_reader_action(deck, [slide], {}, payload, [])

        generate_text.assert_not_called()
        flatten.assert_called_once_with(11, 12)
        rerun.assert_called_once()

    def test_canvas_child_question_validation_error_does_not_crash_reader(self):
        deck = {"id": 3, "title": "信号课件", "subject": "信号与系统"}
        slide = {"id": 9, "slide_number": 2, "title": "周期信号", "slide_text": "本页正文"}
        payload = {
            "action": "canvas_question",
            "deckId": 3,
            "slideNumber": 2,
            "token": "tok-child-limit",
            "question": "还能继续追问吗？",
            "parentQuestionId": 12,
            "quote": {
                "sourceKind": "question_answer",
                "questionId": 12,
                "selectedText": "继续",
            },
        }

        with (
            patch.object(ppt_tutor.st, "session_state", {}),
            patch.object(ppt_tutor.st, "spinner", return_value=nullcontext()),
            patch.object(ppt_tutor.st, "error") as show_error,
            patch.object(ppt_tutor.st, "caption"),
            patch.object(ppt_tutor.st, "rerun") as rerun,
            patch.object(ppt_tutor, "build_slide_context_map", return_value={2: {"same_section": []}}),
            patch.object(ppt_tutor, "_build_branch_prompt", return_value="model prompt"),
            patch.object(ppt_tutor, "generate_text", return_value="回答"),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 11})()),
            patch.object(ppt_tutor, "_active_model_label", return_value="测试模型"),
            patch.object(ppt_tutor, "add_slide_question", side_effect=ValueError("depth exceeded")),
        ):
            ppt_tutor._handle_synced_reader_action(deck, [slide], {}, payload, [])

        show_error.assert_called_once()
        rerun.assert_not_called()

    def test_questions_by_slide_ids_includes_saved_quote_text(self):
        rows = [
            {
                "question": "为什么这里强调周期信号？",
                "quote_text": "周期信号",
                "answer": "回答",
                "model": "模型",
                "category": "",
                "status": "未整理",
                "sort_order": 0,
                "id": 12,
                "root_question_id": 12,
                "parent_question_id": None,
                "depth": 0,
                "quote_source": "slide",
                "quote_source_question_id": None,
                "created_at": "today",
            }
        ]

        with (
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 11})()),
            patch.object(ppt_tutor, "questions_by_slide_ids", return_value={9: rows}),
        ):
            result = ppt_tutor._questions_by_slide_ids([9])

        self.assertEqual(result[9][0]["question"], "为什么这里强调周期信号？")
        self.assertEqual(result[9][0]["quoteText"], "周期信号")
        self.assertEqual(result[9][0]["id"], 12)
        self.assertEqual(result[9][0]["rootQuestionId"], 12)


    def test_build_reader_payload_includes_bookmark_status_with_title_fallback(self):
        slides = [
            {
                "id": 9,
                "slide_number": 2,
                "title": "Signals",
                "slide_text": "",
                "image_path": "",
                "bookmark_enabled": 1,
                "bookmark_title": "",
            }
        ]

        result = ppt_tutor._build_reader_payload(slides, {}, {}, image_slide_numbers=set())

        self.assertTrue(result[0]["bookmarkEnabled"])
        self.assertEqual(result[0]["bookmarkTitle"], "Signals")

    def test_build_reader_payload_normalizes_mineru_latex_for_display(self):
        slides = [
            {
                "id": 9,
                "slide_number": 2,
                "title": "Signals",
                "slide_text": r"通带截止频率\Omega _ { p }、通带衰减\delta _ { 1 }",
                "notes": "source=pdf;extractor=mineru",
                "image_path": "",
            }
        ]

        result = ppt_tutor._build_reader_payload(slides, {}, {}, image_slide_numbers=set())

        self.assertIn(
            r"通带截止频率$\Omega _ { p }$、通带衰减$\delta _ { 1 }$",
            result[0]["slideText"],
        )

    def test_build_reader_payload_repairs_stored_mineru_left_right_fragments(self):
        slides = [
            {
                "id": 9,
                "slide_number": 2,
                "title": "Signals",
                "slide_text": r"stable $\left$| z $\right$| < 1",
                "notes": "source=pdf;extractor=mineru",
                "image_path": "",
            }
        ]

        result = ppt_tutor._build_reader_payload(slides, {}, {}, image_slide_numbers=set())

        self.assertIn(r"$\left| z \right|$", result[0]["slideText"])
        self.assertNotIn(r"$\left$", result[0]["slideText"])
        self.assertNotIn(r"$\right$", result[0]["slideText"])

    def test_build_reader_payload_keeps_full_mineru_text_separate_from_explanation(self):
        long_prefix = "prefix " * 40
        formula = r"\int_0^1 x dx"
        slides = [
            {
                "id": 9,
                "slide_number": 2,
                "title": "Signals",
                "slide_text": f"{long_prefix}{formula}",
                "notes": "source=pdf;extractor=mineru",
                "image_path": "",
            }
        ]

        result = ppt_tutor._build_reader_payload(slides, {}, {}, image_slide_numbers=set())

        self.assertEqual(result[0]["explanation"], "本页还没有 AI 讲解。")
        self.assertFalse(result[0]["hasExplanation"])
        self.assertIn(r"$\int_0^1 x dx$", result[0]["slideText"])
        self.assertNotIn("...", result[0]["slideText"])

    def test_toggle_slide_bookmark_updates_slide_without_model_call(self):
        deck = {"id": 3, "title": "Deck", "subject": "Subject"}
        slide = {"id": 9, "slide_number": 2, "title": "Signals", "slide_text": ""}
        payload = {
            "action": "toggle_slide_bookmark",
            "deckId": 3,
            "slideNumber": 2,
            "token": "tok-bookmark",
            "enabled": True,
        }

        with (
            patch.object(ppt_tutor.st, "session_state", {}),
            patch.object(ppt_tutor.st, "toast"),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 11})()),
            patch.object(ppt_tutor, "generate_text") as generate_text,
            patch.object(ppt_tutor, "update_slide_bookmark") as update_bookmark,
        ):
            ppt_tutor._handle_synced_reader_action(deck, [slide], {}, payload, [])

        generate_text.assert_not_called()
        update_bookmark.assert_called_once_with(11, 9, enabled=True)

    def test_rename_slide_bookmark_updates_title_without_model_call(self):
        deck = {"id": 3, "title": "Deck", "subject": "Subject"}
        slide = {"id": 9, "slide_number": 2, "title": "Signals", "slide_text": ""}
        payload = {
            "action": "rename_slide_bookmark",
            "deckId": 3,
            "slideNumber": 2,
            "token": "tok-bookmark-name",
            "title": "  Chapter start  ",
        }

        with (
            patch.object(ppt_tutor.st, "session_state", {}),
            patch.object(ppt_tutor.st, "toast"),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 11})()),
            patch.object(ppt_tutor, "generate_text") as generate_text,
            patch.object(ppt_tutor, "update_slide_bookmark") as update_bookmark,
        ):
            ppt_tutor._handle_synced_reader_action(deck, [slide], {}, payload, [])

        generate_text.assert_not_called()
        update_bookmark.assert_called_once_with(11, 9, enabled=True, title="Chapter start")


if __name__ == "__main__":
    unittest.main()
