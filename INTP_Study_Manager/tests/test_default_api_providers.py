import unittest
from unittest.mock import patch

from services import ai_service


class DefaultApiProvidersTest(unittest.TestCase):
    def test_seeded_database_gets_mimo_token_plan_backfill(self):
        calls = []

        def fake_fetch_one(query, params=()):
            if "app_settings" in query:
                return {"value": "1"}
            if "COUNT(*)" in query:
                return {"count": 3}
            if "MAX(sort_order)" in query:
                return {"max_order": 3}
            if "WHERE provider_key = ?" in query:
                return None
            return None

        def fake_execute(query, params=()):
            calls.append((query, params))

        with (
            patch.object(ai_service, "fetch_one", side_effect=fake_fetch_one),
            patch.object(ai_service, "fetch_all", return_value=[]),
            patch.object(ai_service, "execute", side_effect=fake_execute),
            patch.object(ai_service, "normalize_api_provider_sort_orders"),
        ):
            ai_service.ensure_default_api_providers()

        inserted = [params for query, params in calls if "INSERT INTO api_providers" in query]
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0][0], ai_service.MIMO_TOKEN_PLAN_PROVIDER_KEY)
        self.assertEqual(inserted[0][1], "MIMO Token Plan")
        self.assertEqual(inserted[0][2], "openai_chat")
        self.assertEqual(inserted[0][3], "https://token-plan-cn.xiaomimimo.com/v1")
        self.assertEqual(inserted[0][4], "mimo-v2.5-pro")
        self.assertEqual(inserted[0][5], "MIMO_TOKEN_PLAN_API_KEY")
        self.assertEqual(inserted[0][6], "api-key")
        self.assertEqual(inserted[0][10], "auto")

    def test_save_api_provider_persists_vision_capability_override(self):
        calls = []

        def fake_execute(query, params=()):
            calls.append((query, params))

        with (
            patch.object(ai_service, "execute", side_effect=fake_execute),
            patch.object(ai_service, "_place_api_provider"),
        ):
            ai_service.save_api_provider(
                {
                    "name": "MiniMax M3",
                    "provider_type": "openai_chat",
                    "base_url": "https://api.minimax.chat/v1",
                    "model": "MiniMax-M3",
                    "api_key_env": "MINIMAX_API_KEY",
                    "auth_type": "bearer",
                    "extra_headers_json": "{}",
                    "request_template_json": "",
                    "response_path": "choices.0.message.content",
                    "vision_capability": "supported",
                    "enabled": True,
                },
                provider_key="minimax",
            )

        update = next(params for query, params in calls if "UPDATE api_providers" in query)
        self.assertEqual(update[9], "supported")

    def test_invalid_vision_capability_falls_back_to_auto(self):
        calls = []

        def fake_execute(query, params=()):
            calls.append((query, params))

        with (
            patch.object(ai_service, "execute", side_effect=fake_execute),
            patch.object(ai_service, "_place_api_provider"),
        ):
            ai_service.save_api_provider(
                {
                    "name": "Unknown",
                    "provider_type": "openai_chat",
                    "vision_capability": "maybe",
                },
                provider_key="unknown",
            )

        update = next(params for query, params in calls if "UPDATE api_providers" in query)
        self.assertEqual(update[9], "auto")


if __name__ == "__main__":
    unittest.main()
