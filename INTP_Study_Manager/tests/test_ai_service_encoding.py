import json
import unittest

from requests import Response

from services.ai_service import _parse_response_json, _repair_utf8_mojibake


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


if __name__ == "__main__":
    unittest.main()
