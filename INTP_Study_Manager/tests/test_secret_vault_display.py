import unittest

from pages import api_settings


class SecretVaultDisplayTest(unittest.TestCase):
    def setUp(self):
        self.providers = [
            {
                "provider_key": "openai-chat",
                "sort_order": 1,
                "name": "OpenAI Chat",
                "model": "gpt-5.5",
                "provider_type": "openai_chat",
                "base_url": "https://api.openai.com/v1",
            },
            {
                "provider_key": "deepseek",
                "sort_order": 2,
                "name": "DeepSeek V4 Pro",
                "model": "deepseek-v4-pro",
                "provider_type": "openai_chat",
                "base_url": "https://api.deepseek.com/v1",
            },
        ]

    def test_rows_are_built_from_saved_keys_not_provider_list(self):
        data = {
            "providers": {
                "2": {
                    "provider_key": "2",
                    "provider_name": "Legacy OpenAI",
                    "model": "gpt-5.5",
                    "provider_type": "openai_chat",
                    "base_url": "https://api.openai.com/v1/",
                    "api_key": "sk-legacy-openai",
                    "updated_at": "2026-05-24T17:00:00",
                },
                "deepseek": {
                    "provider_key": "deepseek",
                    "provider_name": "DeepSeek V4 Pro",
                    "model": "deepseek-v4-pro",
                    "provider_type": "openai_chat",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-deepseek",
                    "updated_at": "2026-05-24T17:01:00",
                },
                "orphan": {
                    "provider_key": "orphan",
                    "provider_name": "Removed Provider",
                    "model": "removed-model",
                    "provider_type": "openai_chat",
                    "base_url": "https://removed.example/v1",
                    "api_key": "sk-removed",
                    "updated_at": "2026-05-24T17:02:00",
                },
            }
        }

        rows = api_settings._secret_vault_rows(self.providers, data)

        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [row["匹配状态"] for row in rows],
            ["已匹配当前 Provider", "已匹配当前 Provider", "未匹配当前 Provider"],
        )
        self.assertEqual(rows[0]["Provider"], "OpenAI Chat")
        self.assertEqual(rows[1]["Provider"], "DeepSeek V4 Pro")
        self.assertEqual(rows[2]["Provider"], "Removed Provider")

    def test_saved_secret_can_match_current_provider_by_name(self):
        item = {
            "provider_key": "9",
            "provider_name": "DeepSeek V4 Pro",
            "api_key": "sk-deepseek",
        }

        provider = api_settings._provider_for_saved_secret(self.providers, "9", item)

        self.assertEqual(provider["provider_key"], "deepseek")


if __name__ == "__main__":
    unittest.main()
