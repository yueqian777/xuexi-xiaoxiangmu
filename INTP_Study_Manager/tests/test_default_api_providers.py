import unittest
from unittest.mock import patch

from services import balance_service
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
            ai_service.ensure_default_api_providers(user_id=7)

        inserted = [params for query, params in calls if "INSERT INTO api_providers" in query]
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0][0], ai_service.MIMO_TOKEN_PLAN_PROVIDER_KEY)
        self.assertEqual(inserted[0][1], 7)
        self.assertEqual(inserted[0][2], "MIMO Token Plan")
        self.assertEqual(inserted[0][3], "openai_chat")
        self.assertEqual(inserted[0][4], "https://token-plan-cn.xiaomimimo.com/v1")
        self.assertEqual(inserted[0][5], "mimo-v2.5-pro")
        self.assertEqual(inserted[0][6], "MIMO_TOKEN_PLAN_API_KEY")
        self.assertEqual(inserted[0][7], "api-key")
        self.assertEqual(inserted[0][11], "auto")

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
                user_id=7,
            )

        query, update = next((query, params) for query, params in calls if "UPDATE api_providers" in query)
        self.assertIn("WHERE provider_key = ? AND user_id = ?", query)
        self.assertEqual(update[9], "supported")
        self.assertEqual(update[-2:], ("minimax", 7))

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
                user_id=7,
            )

        query, update = next((query, params) for query, params in calls if "UPDATE api_providers" in query)
        self.assertIn("WHERE provider_key = ? AND user_id = ?", query)
        self.assertEqual(update[9], "auto")
        self.assertEqual(update[-2:], ("unknown", 7))

    def test_list_enabled_api_providers_scopes_to_user_id(self):
        calls = []

        def fake_fetch_all(query, params=()):
            calls.append((query, params))
            return []

        with (
            patch.object(ai_service, "fetch_all", side_effect=fake_fetch_all),
            patch.object(ai_service, "normalize_api_provider_sort_orders") as normalize,
        ):
            ai_service.list_api_providers(enabled_only=True, user_id=7)

        query, params = calls[0]
        self.assertIn("WHERE user_id = ?", query)
        self.assertIn("AND enabled = 1", query)
        self.assertEqual(params, (7,))
        normalize.assert_called_once_with(user_id=7)

    def test_get_api_provider_scopes_explicit_key_to_user_id(self):
        calls = []
        row = {
            "provider_key": "cliproxy",
            "name": "CLIProxy",
            "provider_type": "openai_chat",
            "base_url": "http://localhost:8317/v1",
            "model": "gpt-5.5",
            "api_key_env": "CLIPROXY_API_KEY",
            "auth_type": "bearer",
            "extra_headers_json": "{}",
            "request_template_json": "",
            "response_path": "choices.0.message.content",
            "vision_capability": "auto",
            "enabled": 1,
        }

        def fake_fetch_one(query, params=()):
            calls.append((query, params))
            return row

        with patch.object(ai_service, "fetch_one", side_effect=fake_fetch_one):
            provider = ai_service.get_api_provider("cliproxy", user_id=7)

        self.assertEqual(provider.provider_key, "cliproxy")
        query, params = calls[0]
        self.assertIn("WHERE provider_key = ? AND user_id = ?", query)
        self.assertEqual(params, ("cliproxy", 7))

    def test_delete_api_providers_scopes_to_user_id(self):
        calls = []

        def fake_execute_many(query, params_iter):
            calls.append((query, list(params_iter)))

        with (
            patch.object(ai_service, "execute_many", side_effect=fake_execute_many),
            patch.object(ai_service, "normalize_api_provider_sort_orders") as normalize,
        ):
            deleted = ai_service.delete_api_providers(["cliproxy"], user_id=7)

        self.assertEqual(deleted, 1)
        query, params = calls[0]
        self.assertIn("WHERE provider_key = ? AND user_id = ?", query)
        self.assertEqual(params, [("cliproxy", 7)])
        normalize.assert_called_once_with(user_id=7)

    def test_balance_query_config_update_scopes_to_user_id(self):
        calls = []

        def fake_execute(query, params=()):
            calls.append((query, params))

        with patch.object(balance_service, "execute", side_effect=fake_execute):
            balance_service.save_balance_query_config(
                "cliproxy",
                enabled=True,
                query_type="generic_wallet",
                config={"custom_url": "https://example.test/balance"},
                user_id=7,
            )

        query, params = calls[0]
        self.assertIn("WHERE provider_key = ? AND user_id = ?", query)
        self.assertEqual(params[-2:], ("cliproxy", 7))


if __name__ == "__main__":
    unittest.main()
