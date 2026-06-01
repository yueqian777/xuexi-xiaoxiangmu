import unittest

from pages import ppt_tutor


class ProviderVisionCapabilityTest(unittest.TestCase):
    def test_supported_override_allows_new_model_without_name_marker(self):
        provider = {
            "provider_type": "openai_chat",
            "model": "MiniMax-M3",
            "vision_capability": "supported",
        }

        self.assertTrue(ppt_tutor._provider_supports_image_input(provider, "MiniMax-M3"))

    def test_unsupported_override_blocks_model_that_looks_visual(self):
        provider = {
            "provider_type": "openai_chat",
            "model": "gpt-5",
            "vision_capability": "unsupported",
        }

        self.assertFalse(ppt_tutor._provider_supports_image_input(provider, "gpt-5"))

    def test_auto_keeps_existing_model_name_inference(self):
        provider = {
            "provider_type": "openai_chat",
            "model": "qwen-vl-plus",
            "vision_capability": "auto",
        }

        self.assertTrue(ppt_tutor._provider_supports_image_input(provider, "qwen-vl-plus"))


if __name__ == "__main__":
    unittest.main()
