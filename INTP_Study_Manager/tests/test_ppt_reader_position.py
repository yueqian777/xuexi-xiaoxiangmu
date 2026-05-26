import json
import unittest
from unittest.mock import patch

from pages import ppt_tutor


class PptReaderPositionTest(unittest.TestCase):
    def test_read_last_reader_position_accepts_positive_ids(self):
        payload = json.dumps({"deck_id": "7", "slide_number": "12"})
        with patch.object(ppt_tutor, "fetch_one", return_value={"value": payload}):
            self.assertEqual(
                ppt_tutor._read_last_reader_position(42),
                {"deck_id": 7, "slide_number": 12},
            )

    def test_read_last_reader_position_ignores_bad_json(self):
        with patch.object(ppt_tutor, "fetch_one", return_value={"value": "not-json"}):
            self.assertEqual(ppt_tutor._read_last_reader_position(42), {})

    def test_save_last_reader_position_keeps_slide_for_same_deck(self):
        with (
            patch.object(ppt_tutor, "_read_last_reader_position", return_value={"deck_id": 3, "slide_number": 9}),
            patch.object(ppt_tutor, "execute") as execute,
        ):
            ppt_tutor._save_last_reader_position(42, 3)

        execute.assert_not_called()

    def test_save_last_reader_position_writes_new_deck_without_old_slide(self):
        with (
            patch.object(ppt_tutor, "_read_last_reader_position", return_value={"deck_id": 3, "slide_number": 9}),
            patch.object(ppt_tutor, "execute") as execute,
        ):
            ppt_tutor._save_last_reader_position(42, 4)

        args = execute.call_args.args
        self.assertEqual(json.loads(args[1][2]), {"deck_id": 4})

    def test_initial_reader_slide_number_uses_valid_remembered_slide(self):
        slides = [{"slide_number": 1}, {"slide_number": 5}]

        self.assertEqual(
            ppt_tutor._initial_reader_slide_number(2, slides, {"deck_id": 2, "slide_number": 5}),
            5,
        )

    def test_initial_reader_slide_number_falls_back_to_first_slide(self):
        slides = [{"slide_number": 1}, {"slide_number": 5}]

        self.assertEqual(
            ppt_tutor._initial_reader_slide_number(2, slides, {"deck_id": 2, "slide_number": 99}),
            1,
        )

    def test_reader_payload_exposes_structure_fields_for_component(self):
        payload = ppt_tutor._build_reader_payload(
            [
                {
                    "id": 10,
                    "slide_number": 3,
                    "title": "ROC",
                    "slide_text": "收敛域",
                    "image_path": "",
                    "section_index": 2,
                    "page_type": "正文页",
                    "one_sentence_summary": "解释 ROC",
                    "slide_role": "承接定义",
                    "key_points": "边界条件",
                }
            ],
            {},
            {10: []},
        )

        self.assertEqual(payload[0]["sectionIndex"], 2)
        self.assertEqual(payload[0]["pageType"], "正文页")
        self.assertEqual(payload[0]["summary"], "解释 ROC")
        self.assertEqual(payload[0]["slideRole"], "承接定义")
        self.assertEqual(payload[0]["keyPoints"], "边界条件")

    def test_reader_payload_only_embeds_images_in_active_window(self):
        slides = [
            {"id": 1, "slide_number": 1, "title": "A", "slide_text": "", "image_path": "a.png"},
            {"id": 2, "slide_number": 2, "title": "B", "slide_text": "", "image_path": "b.png"},
        ]
        with (
            patch.object(ppt_tutor.Path, "exists", return_value=True),
            patch.object(ppt_tutor.Path, "is_file", return_value=True),
            patch.object(ppt_tutor, "_image_data_uri", side_effect=lambda path: f"data:{path}"),
        ):
            payload = ppt_tutor._build_reader_payload(
                slides,
                {},
                {},
                image_slide_numbers={2},
            )

        self.assertTrue(payload[0]["imageAvailable"])
        self.assertEqual(payload[0]["image"], "")
        self.assertEqual(payload[1]["image"], "data:b.png")

    def test_reader_sections_payload_uses_component_key_names(self):
        payload = ppt_tutor._reader_sections_payload(
            [
                {
                    "section_index": 1,
                    "title": "Z 变换基础",
                    "start_slide": 1,
                    "end_slide": 8,
                    "core_question": "为什么需要 Z 变换？",
                    "summary": "从序列到复频域。",
                }
            ]
        )

        self.assertEqual(
            payload[0],
            {
                "sectionIndex": 1,
                "title": "Z 变换基础",
                "startSlide": 1,
                "endSlide": 8,
                "coreQuestion": "为什么需要 Z 变换？",
                "summary": "从序列到复频域。",
            },
        )

    def test_slide_prompt_replaces_context_package_placeholder(self):
        context = {
            "deck_title": "Z 变换",
            "section": {
                "title": "收敛域",
                "start_slide": 3,
                "end_slide": 6,
                "core_question": "ROC 怎么决定系统性质？",
            },
            "slide": {"slide_number": 3, "title": "ROC 定义"},
        }
        with (
            patch.object(ppt_tutor, "_related_knowledge_context", return_value="暂无同科目知识卡片。"),
            patch.object(ppt_tutor, "_image_exists", return_value=False),
        ):
            prompt = ppt_tutor._build_slide_prompt(
                {"title": "Z 变换", "subject": "信号与系统"},
                {"slide_number": 3, "title": "ROC 定义", "slide_text": "ROC 是收敛域。"},
                context=context,
            )

        self.assertNotIn("{context_package}", prompt)
        self.assertIn("当前目录块：收敛域", prompt)
        self.assertIn("ROC 怎么决定系统性质？", prompt)

    def test_document_structure_generation_fills_prompt_variables(self):
        captured = {}

        def fake_generate_text(prompt, **kwargs):
            captured["prompt"] = prompt
            return json.dumps(
                {
                    "outline": "大纲",
                    "sections": [
                        {
                            "section_index": 1,
                            "title": "整体",
                            "start_slide": 1,
                            "end_slide": 2,
                        }
                    ],
                },
                ensure_ascii=False,
            )

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "save_deck_structure") as save_deck_structure,
        ):
            ppt_tutor._generate_document_structure(
                {"id": 5, "title": "Z 变换", "subject": "信号与系统"},
                [
                    {"slide_number": 1, "title": "第一页", "slide_text": "内容 A"},
                    {"slide_number": 2, "title": "第二页", "slide_text": "内容 B"},
                ],
                provider_key="test",
                api_key="key",
                active_model="model",
                max_tokens=4096,
                reasoning_depth="关闭",
            )

        self.assertNotIn("{slide_count}", captured["prompt"])
        self.assertNotIn("{page_list}", captured["prompt"])
        self.assertIn("总页数：2", captured["prompt"])
        self.assertIn("第 1 页", captured["prompt"])
        save_deck_structure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
