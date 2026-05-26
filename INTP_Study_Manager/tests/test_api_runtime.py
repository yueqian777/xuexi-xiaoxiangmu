import unittest
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


if __name__ == "__main__":
    unittest.main()
