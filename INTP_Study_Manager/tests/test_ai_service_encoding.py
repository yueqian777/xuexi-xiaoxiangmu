import json
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch

from requests import Response

if "streamlit" not in sys.modules and importlib.util.find_spec("streamlit") is None:
    streamlit_stub = types.ModuleType("streamlit")
    streamlit_stub.session_state = {}
    sys.modules["streamlit"] = streamlit_stub

from services.ai_service import (
    AIServiceError,
    AIProvider,
    MIMO_TOKEN_PLAN_PROVIDER_KEY,
    MIMO_TOKEN_PLAN_MODELS,
    _build_request,
    _extract_text_output,
    _parse_response_json,
    _repair_utf8_mojibake,
    generate_text,
    list_available_models,
)


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

    def test_mimo_token_plan_request_uses_api_key_header(self):
        provider = AIProvider(
            provider_key=MIMO_TOKEN_PLAN_PROVIDER_KEY,
            name="MIMO Token Plan",
            provider_type="openai_chat",
            base_url="https://token-plan-cn.xiaomimimo.com/v1",
            model="mimo-v2.5-pro",
            api_key_env="MIMO_TOKEN_PLAN_API_KEY",
            auth_type="api-key",
            extra_headers_json="{}",
            request_template_json="",
            response_path="choices.0.message.content",
        )

        request = _build_request(provider, "ping", "tp-test", "mimo-v2.5-pro", 64, [])

        self.assertEqual(request["url"], "https://token-plan-cn.xiaomimimo.com/v1/chat/completions")
        self.assertEqual(request["headers"].get("api-key"), "tp-test")
        self.assertNotIn("Authorization", request["headers"])
        self.assertEqual(request["json"]["model"], "mimo-v2.5-pro")
        self.assertEqual(request["json"]["max_completion_tokens"], 64)
        self.assertNotIn("max_tokens", request["json"])

    def test_mimo_token_plan_models_are_local_known_models(self):
        provider = {
            "provider_key": MIMO_TOKEN_PLAN_PROVIDER_KEY,
            "provider_type": "openai_chat",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key_env": "MIMO_TOKEN_PLAN_API_KEY",
        }

        self.assertEqual(list_available_models(provider, api_key=""), MIMO_TOKEN_PLAN_MODELS)

    def test_generate_text_allows_long_running_request_timeout_override(self):
        provider = AIProvider(
            provider_key="local",
            name="Local",
            provider_type="openai_chat",
            base_url="http://localhost:8317/v1",
            model="model-a",
            api_key_env="",
            auth_type="none",
            extra_headers_json="{}",
            request_template_json="",
            response_path="choices.0.message.content",
        )
        response = Response()
        response.status_code = 200
        response._content = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

        with (
            patch("services.ai_service.get_api_provider", return_value=provider),
            patch("services.ai_service.requests.request", return_value=response) as request,
        ):
            output = generate_text("ping", request_timeout=300)

        self.assertEqual(output, "ok")
        self.assertEqual(request.call_args.kwargs["timeout"], 300)

    def test_generate_text_surfaces_responses_status_when_no_text_is_returned(self):
        provider = AIProvider(
            provider_key="responses",
            name="Responses",
            provider_type="openai_responses",
            base_url="https://api.example.com/v1",
            model="model-a",
            api_key_env="",
            auth_type="none",
            extra_headers_json="{}",
            request_template_json="",
            response_path="choices.0.message.content",
        )
        response = Response()
        response.status_code = 200
        response._content = json.dumps(
            {
                "status": "failed",
                "error": {"message": "upstream route failed", "type": "api_error"},
                "output": [],
            }
        ).encode("utf-8")

        with (
            patch("services.ai_service.get_api_provider", return_value=provider),
            patch("services.ai_service.requests.request", return_value=response),
            self.assertRaises(AIServiceError) as raised,
        ):
            generate_text("ping")

        message = str(raised.exception)
        self.assertIn("status=failed", message)
        self.assertIn("upstream route failed", message)
        self.assertIn("output_len=0", message)


if __name__ == "__main__":
    unittest.main()
