import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services import secret_store


class SecretStoreLegacyMigrationTest(unittest.TestCase):
    def test_legacy_global_secret_store_is_visible_and_migrated(self):
        if not secret_store.CRYPTOGRAPHY_AVAILABLE:
            self.skipTest("cryptography is not installed")

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            legacy_path = data_dir / "api_keys.enc.json"
            user_path = data_dir / "api_keys_user_1.enc.json"
            provider_data = {
                "providers": {
                    "local-cliproxy": {
                        "provider_key": "local-cliproxy",
                        "provider_name": "本地 CLIProxyAPI",
                        "provider_type": "openai-compatible",
                        "base_url": "http://localhost:8317/v1",
                        "model": "gpt-5.5",
                        "api_key": "test-secret-key",
                    }
                }
            }

            with (
                patch.object(secret_store, "DATA_DIR", data_dir),
                patch.object(secret_store, "SECRET_STORE_PATH", legacy_path),
                patch.object(secret_store, "require_login", return_value=SimpleNamespace(id=1)),
            ):
                secret_store.save_secret_store("test-master-password", provider_data)
                user_path.replace(legacy_path)

                self.assertFalse(user_path.exists())
                self.assertTrue(secret_store.secret_store_exists())
                public_index = secret_store.load_secret_public_index()
                self.assertEqual(public_index[0]["provider_key"], "local-cliproxy")

                loaded = secret_store.load_secret_store("test-master-password")

            self.assertEqual(loaded["providers"]["local-cliproxy"]["provider_name"], "本地 CLIProxyAPI")
            self.assertTrue(user_path.exists())

    def test_legacy_global_secret_store_for_other_user_is_hidden(self):
        if not secret_store.CRYPTOGRAPHY_AVAILABLE:
            self.skipTest("cryptography is not installed")

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            legacy_path = data_dir / "api_keys.enc.json"
            user_two_path = data_dir / "api_keys_user_2.enc.json"
            provider_data = {
                "providers": {
                    "other-provider": {
                        "provider_key": "other-provider",
                        "provider_name": "Other Provider",
                        "api_key": "other-secret-key",
                    }
                }
            }

            with (
                patch.object(secret_store, "DATA_DIR", data_dir),
                patch.object(secret_store, "SECRET_STORE_PATH", legacy_path),
                patch.object(secret_store, "require_login", return_value=SimpleNamespace(id=1)),
            ):
                secret_store.save_secret_store("test-master-password", provider_data)
                (data_dir / "api_keys_user_1.enc.json").replace(legacy_path)

            with (
                patch.object(secret_store, "DATA_DIR", data_dir),
                patch.object(secret_store, "SECRET_STORE_PATH", legacy_path),
                patch.object(secret_store, "require_login", return_value=SimpleNamespace(id=2)),
            ):
                self.assertFalse(secret_store.secret_store_exists())
                self.assertEqual(secret_store.load_secret_public_index(), [])
                self.assertEqual(secret_store.load_secret_store("test-master-password"), {"providers": {}})

            self.assertFalse(user_two_path.exists())


if __name__ == "__main__":
    unittest.main()
