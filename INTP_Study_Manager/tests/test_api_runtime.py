import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import api_runtime
from services.ai_service import DEFAULT_MODEL


class _LockedWidgetState(dict):
    def __init__(self, locked_keys=()):
        super().__init__()
        self.locked_keys = set(locked_keys)

    def __setitem__(self, key, value):
        if key in self.locked_keys:
            raise AssertionError(f"widget key was modified after instantiation: {key}")
        super().__setitem__(key, value)


class _FakeStreamlit:
    def __init__(self, session_state):
        self.session_state = session_state


class ApiRuntimeProviderModelTest(unittest.TestCase):
    def test_ensure_provider_model_does_not_mutate_widget_state_after_instantiation(self):
        provider = {"provider_key": "本地-cliproxyapi", "model": "qwen-local"}
        key = api_runtime.provider_model_state_key(provider["provider_key"])
        session_state = _LockedWidgetState(locked_keys={key})
        dict.__setitem__(session_state, key, "qwen-local")

        with patch.object(api_runtime, "st", _FakeStreamlit(session_state)):
            self.assertEqual(api_runtime.ensure_provider_model(provider), "qwen-local")

    def test_ensure_provider_model_initializes_missing_state_before_widget_exists(self):
        provider = {"provider_key": "new-provider", "model": ""}
        key = api_runtime.provider_model_state_key(provider["provider_key"])
        session_state = _LockedWidgetState()

        with patch.object(api_runtime, "st", _FakeStreamlit(session_state)):
            self.assertEqual(api_runtime.ensure_provider_model(provider), DEFAULT_MODEL)

        self.assertEqual(session_state[key], DEFAULT_MODEL)


class ApiRuntimeDefaultConfigTest(unittest.TestCase):
    def test_get_default_api_config_migrates_legacy_global_setting(self):
        calls = []
        legacy = {"value": '{"provider_key": "sub2api-243706", "model": "gpt-5.4"}'}

        def fake_fetch_one(_sql, params):
            calls.append(params[0])
            if params[0] == "user:1:default_api_config":
                return None
            if params[0] == "default_api_config":
                return legacy
            return None

        with (
            patch.object(api_runtime, "require_login", return_value=SimpleNamespace(id=1)),
            patch.object(api_runtime, "fetch_one", side_effect=fake_fetch_one),
            patch.object(api_runtime, "execute") as execute,
        ):
            config = api_runtime.get_default_api_config()

        self.assertEqual(config, {"provider_key": "sub2api-243706", "model": "gpt-5.4"})
        self.assertEqual(calls, ["user:1:default_api_config", "default_api_config"])
        execute.assert_called_once()
        self.assertIn("user:1:default_api_config", execute.call_args.args[1])

    def test_get_default_api_config_prefers_user_scoped_setting(self):
        rows = {
            "user:1:default_api_config": {"value": '{"provider_key": "user-provider", "model": "user-model"}'},
            "default_api_config": {"value": '{"provider_key": "legacy-provider", "model": "legacy-model"}'},
        }

        with (
            patch.object(api_runtime, "require_login", return_value=SimpleNamespace(id=1)),
            patch.object(api_runtime, "fetch_one", side_effect=lambda _sql, params: rows.get(params[0])),
            patch.object(api_runtime, "execute") as execute,
        ):
            config = api_runtime.get_default_api_config()

        self.assertEqual(config, {"provider_key": "user-provider", "model": "user-model"})
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
