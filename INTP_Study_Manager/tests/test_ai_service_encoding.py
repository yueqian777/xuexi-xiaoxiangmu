import json
import sys
import types
import unittest

from requests import Response

if "streamlit" not in sys.modules:
    streamlit_stub = types.ModuleType("streamlit")
    streamlit_stub.session_state = {}
    sys.modules["streamlit"] = streamlit_stub

from services.ai_service import _extract_text_output, _parse_response_json, _repair_utf8_mojibake


class AIServiceEncodingTest(unittest.TestCase):
    def test_parse_response_json_prefers_utf8_over_latin1_header(self):
        expected = "第 11 页：本页核心，怎么理解 “状态机”"
        body = json.dumps(
            {"choices": [{"message": {"content": expected}}]},
            ensure_ascii=False,
        ).encode("utf-8")
        response = Response()
        response.status_code = 200
        response._content = body
        response.headers["Content-Type"] = "application/json"
        response.encoding = "ISO-8859-1"

        payload = _parse_response_json(response)

        self.assertEqual(payload["choices"][0]["message"]["content"], expected)

    def test_repair_utf8_mojibake_in_model_output(self):
        expected = "第 11 页：本页核心，怎么理解 “状态机”"
        mojibake = expected.encode("utf-8").decode("latin-1")

        self.assertEqual(_repair_utf8_mojibake(mojibake), expected)

    def test_repair_utf8_mojibake_leaves_normal_text_unchanged(self):
        expected = "第 11 页：本页核心，怎么理解 “状态机”"

        self.assertEqual(_repair_utf8_mojibake(expected), expected)

    def test_extract_text_output_falls_back_from_chat_path_to_responses_output_text(self):
        output, path = _extract_text_output(
            {"output_text": "目录 JSON"},
            "choices.0.message.content",
            "openai_chat",
        )

        self.assertEqual(output, "目录 JSON")
        self.assertEqual(path, "output_text")

    def test_extract_text_output_falls_back_from_responses_path_to_chat_choices(self):
        output, path = _extract_text_output(
            {"choices": [{"message": {"content": "目录 JSON"}}]},
            "output_text",
            "openai_responses",
        )

        self.assertEqual(output, "目录 JSON")
        self.assertEqual(path, "choices.0.message.content")

    def test_extract_text_output_handles_nested_content_parts(self):
        output, path = _extract_text_output(
            {"message": {"content": [{"type": "text", "text": "目录 JSON"}]}},
            "choices.0.message.content",
            "openai_chat",
        )

        self.assertEqual(output, "目录 JSON")
        self.assertEqual(path, "message.content")

    def test_extract_text_output_joins_openai_responses_output_items(self):
        output, path = _extract_text_output(
            {
                "output": [
                    {"type": "reasoning", "summary": []},
                    {"type": "message", "content": [{"type": "output_text", "text": "目录 JSON"}]},
                ]
            },
            "choices.0.message.content",
            "openai_chat",
        )

        self.assertEqual(output, "目录 JSON")
        self.assertEqual(path, "output")


if __name__ == "__main__":
    unittest.main()
