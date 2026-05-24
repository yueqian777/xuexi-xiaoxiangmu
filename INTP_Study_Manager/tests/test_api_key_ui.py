import unittest
from unittest.mock import patch

from services import api_key_ui


class LocalSecretMatchingTest(unittest.TestCase):
    def setUp(self):
        self.provider = {
            "provider_key": "openai-compatible",
            "name": "OpenAI Compatible",
            "model": "gpt-5.5",
            "provider_type": "openai_chat",
            "base_url": "https://api.example.com/v1",
        }

    def test_no_secret_store_has_no_candidates(self):
        with patch.object(api_key_ui, "secret_store_exists", return_value=False):
            self.assertFalse(api_key_ui.has_matching_local_secret(self.provider, model="gpt-5.5"))

    def test_matches_public_index_by_provider_key(self):
        public_index = [
            {
                "provider_key": "openai-compatible",
                "provider_name": "OpenAI Compatible",
                "model": "gpt-5.5",
                "provider_type": "openai_chat",
                "base_url": "https://api.example.com/v1",
            }
        ]
        with (
            patch.object(api_key_ui, "secret_store_exists", return_value=True),
            patch.object(api_key_ui, "load_secret_public_index", return_value=public_index),
            patch.object(api_key_ui, "_unlocked_secret_data", return_value=None),
        ):
            candidates = api_key_ui.find_local_secret_candidates(self.provider, model="gpt-5.5")

        self.assertEqual(candidates[0]["provider_key"], "openai-compatible")

    def test_matches_legacy_public_index_by_provider_shape(self):
        public_index = [
            {
                "provider_id": "2",
                "provider_name": "Old Provider",
                "model": "gpt-5.5",
                "provider_type": "openai_chat",
                "base_url": "https://api.example.com/v1/",
            }
        ]
        with (
            patch.object(api_key_ui, "secret_store_exists", return_value=True),
            patch.object(api_key_ui, "load_secret_public_index", return_value=public_index),
            patch.object(api_key_ui, "_unlocked_secret_data", return_value=None),
        ):
            candidates = api_key_ui.find_local_secret_candidates(self.provider, model="gpt-5.5")

        self.assertEqual(candidates[0]["provider_key"], "2")

    def test_unrelated_public_index_does_not_match(self):
        public_index = [
            {
                "provider_key": "other",
                "provider_name": "Other",
                "model": "claude",
                "provider_type": "anthropic_messages",
                "base_url": "https://api.other.example/v1",
            }
        ]
        with (
            patch.object(api_key_ui, "secret_store_exists", return_value=True),
            patch.object(api_key_ui, "load_secret_public_index", return_value=public_index),
            patch.object(api_key_ui, "_unlocked_secret_data", return_value=None),
        ):
            self.assertFalse(api_key_ui.has_matching_local_secret(self.provider, model="gpt-5.5"))


if __name__ == "__main__":
    unittest.main()
