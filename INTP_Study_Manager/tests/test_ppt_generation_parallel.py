import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.ai_service import AIServiceError
from services import api_runtime
from pages import ppt_tutor


APP_ROOT = Path(__file__).resolve().parents[1]


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _FakeStreamlit:
    def __init__(self, task):
        self.session_state = {"ppt_generation_task": task}
        self.rerun_called = False

    def success(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def progress(self, *args, **kwargs):
        pass

    def caption(self, *args, **kwargs):
        pass

    def columns(self, *args, **kwargs):
        return [_Context(), _Context()]

    def button(self, *args, **kwargs):
        return False

    def rerun(self):
        self.rerun_called = True


class _LockedWidgetState(dict):
    def __init__(self, locked_keys=()):
        super().__init__()
        self.locked_keys = set(locked_keys)

    def __setitem__(self, key, value):
        if key in self.locked_keys:
            raise AssertionError(f"widget key was modified after instantiation: {key}")
        super().__setitem__(key, value)


class PptGenerationParallelTest(unittest.TestCase):
    def test_generation_ui_does_not_expose_retry_choice_or_attempt_count(self):
        source = (APP_ROOT / "pages" / "ppt_tutor.py").read_text(encoding="utf-8")

        self.assertNotIn("错误页自动重试", source)
        self.assertNotIn("错误页最多重试次数", source)

    def test_generation_parallelism_is_clamped_to_safe_target_count(self):
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(None, 10), 1)
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(0, 10), 1)
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(3, 2), 2)
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(99, 20), 20)
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(99, 50, max_parallelism=40), 40)

    def test_provider_parallel_limit_defaults_to_eight_without_benchmark(self):
        provider = {
            "provider_key": "generic",
            "name": "Generic Provider",
            "provider_type": "unknown",
            "base_url": "https://api.example.com/v1",
            "model": "slow-thinking-model",
        }

        self.assertEqual(ppt_tutor._provider_parallel_limit(provider), 8)

    def test_adaptive_parallelism_uses_selected_provider_group_capacity(self):
        provider_pool = [
            {"provider_key": "fast-a", "parallel_limit": 5},
            {"provider_key": "fast-b", "parallel_limit": 4},
            {"provider_key": "slow-c", "parallel_limit": 2},
        ]

        self.assertEqual(ppt_tutor._adaptive_generation_parallelism(provider_pool, 20), 11)
        self.assertEqual(ppt_tutor._adaptive_generation_parallelism(provider_pool, 3), 3)

    def test_adaptive_parallelism_has_no_global_cap(self):
        provider_pool = [
            {"provider_key": "a", "parallel_limit": 20},
            {"provider_key": "b", "parallel_limit": 18},
        ]

        self.assertEqual(ppt_tutor._adaptive_generation_parallelism(provider_pool, 100), 38)

    def test_parallel_benchmark_starts_near_default_and_uses_success_threshold(self):
        provider = {
            "provider_key": "bench",
            "provider_name": "Benchmark",
            "api_key": "key",
            "active_model": "model",
            "active_model_label": "Benchmark / model",
            "parallel_limit": 8,
        }
        active_calls = 0

        def fake_request(prompt, **kwargs):
            nonlocal active_calls
            active_calls += 1
            try:
                if active_calls > 6:
                    raise AIServiceError("rate limit", category="rate_limit")
                time.sleep(0.02)
                return "ok"
            finally:
                active_calls -= 1

        result = ppt_tutor._probe_provider_parallel_limit(
            provider,
            max_parallelism=8,
            request_func=fake_request,
        )

        self.assertEqual([probe["concurrency"] for probe in result["probes"][:2]], [8, 6])
        self.assertEqual(result["parallel_limit"], 6)
        self.assertTrue(result["ok"])

    def test_parallel_benchmark_group_sums_measured_provider_limits(self):
        provider_pool = [
            {
                "provider_key": "a",
                "provider_name": "Provider A",
                "api_key": "key-a",
                "active_model": "model-a",
                "active_model_label": "Provider A / model-a",
                "parallel_limit": 8,
            },
            {
                "provider_key": "b",
                "provider_name": "Provider B",
                "api_key": "key-b",
                "active_model": "model-b",
                "active_model_label": "Provider B / model-b",
                "parallel_limit": 8,
            },
        ]
        limits = {"a": 2, "b": 4}
        active_by_provider = {"a": 0, "b": 0}

        def fake_request(prompt, **kwargs):
            provider_key = kwargs["provider_key"]
            active_by_provider[provider_key] += 1
            try:
                if active_by_provider[provider_key] > limits[provider_key]:
                    raise AIServiceError("rate limit", category="rate_limit")
                time.sleep(0.02)
                return "ok"
            finally:
                active_by_provider[provider_key] -= 1

        result = ppt_tutor._benchmark_generation_provider_pool(
            provider_pool,
            max_parallelism=5,
            request_func=fake_request,
        )

        self.assertEqual(result["group_parallel_limit"], 6)
        self.assertEqual({item["provider_key"]: item["parallel_limit"] for item in result["providers"]}, {"a": 2, "b": 4})

    def test_measured_parallel_limits_are_applied_to_provider_pool(self):
        provider_pool = [
            {"provider_key": "a", "base_url": "https://a.example/v1", "active_model": "model-a", "parallel_limit": 8},
            {"provider_key": "b", "base_url": "https://b.example/v1", "active_model": "model-b", "parallel_limit": 8},
        ]
        benchmark_results = {
            ppt_tutor._parallel_benchmark_key(provider_pool[0]): {"parallel_limit": 12},
        }

        applied = ppt_tutor._apply_parallel_benchmark_results(provider_pool, benchmark_results)

        self.assertEqual(applied[0]["parallel_limit"], 12)
        self.assertEqual(applied[1]["parallel_limit"], 8)

    def test_generation_provider_pool_keeps_active_provider_first(self):
        providers = [
            {
                "provider_key": "a",
                "name": "Provider A",
                "provider_type": "openai_chat",
                "base_url": "https://api.a.example/v1",
                "model": "gpt-5",
                "api_key_env": "",
            },
            {
                "provider_key": "b",
                "name": "Provider B",
                "provider_type": "openai_chat",
                "base_url": "https://api.b.example/v1",
                "model": "gpt-5",
                "api_key_env": "",
            },
        ]

        pool = ppt_tutor._build_generation_provider_pool(
            providers,
            selected_provider_keys=["b", "a"],
            active_provider_key="a",
            api_keys_by_provider={"a": "key-a", "b": "key-b"},
            models_by_provider={"a": "model-a", "b": "model-b"},
        )

        self.assertEqual([item["provider_key"] for item in pool], ["a", "b"])
        self.assertEqual(pool[0]["api_key"], "key-a")
        self.assertEqual(pool[1]["active_model"], "model-b")

    def test_generation_provider_pool_does_not_mutate_instantiated_model_widget(self):
        provider_key = "本地-cliproxyapi"
        model_key = ppt_tutor.provider_model_state_key(provider_key)
        providers = [
            {
                "provider_key": provider_key,
                "name": "本地 CLIProxyAPI",
                "provider_type": "openai_chat",
                "base_url": "http://localhost:8317/v1",
                "model": "qwen-local",
                "api_key_env": "",
                "enabled": 1,
            }
        ]
        session_state = _LockedWidgetState(locked_keys={model_key})
        dict.__setitem__(session_state, model_key, "qwen-local")
        dict.__setitem__(session_state, f"api_key_provider_{provider_key}", "local-key")

        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(api_runtime.st, "session_state", session_state),
        ):
            pool = ppt_tutor._build_generation_provider_pool(
                providers,
                selected_provider_keys=[provider_key],
                active_provider_key=provider_key,
            )

        self.assertEqual(pool[0]["provider_key"], provider_key)
        self.assertEqual(pool[0]["active_model"], "qwen-local")
        self.assertEqual(pool[0]["api_key"], "local-key")

    def test_running_generation_status_does_not_block_page_render(self):
        task = {
            "status": "running",
            "progress": 0.25,
            "status_text": "正在分析第 2 页...",
            "generated": 1,
            "skipped": 0,
            "failed": 0,
            "parallelism": 2,
        }
        fake_st = _FakeStreamlit(task)

        with patch.object(ppt_tutor, "st", fake_st):
            returned = ppt_tutor._resume_interrupted_generation()

        self.assertIs(returned, task)
        self.assertFalse(fake_st.rerun_called)

    def test_background_generation_worker_runs_slide_requests_in_parallel(self):
        task = {
            "status": "running",
            "progress": 0.0,
            "status_text": "",
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "parallelism": 2,
            "send_image_when_no_text": False,
            "force_image_input": False,
            "supports_image_input": False,
            "provider_key": "test-provider",
            "api_key": "test-key",
            "active_model": "test-model",
            "max_tokens": 100,
            "active_model_label": "测试模型",
            "reasoning_depth": "关闭",
            "context_by_slide": {},
            "related_knowledge": "",
            "user_id": 7,
            "stop_requested": False,
        }
        slides = [
            {"id": 1, "slide_number": 1, "title": "A", "slide_text": "text"},
            {"id": 2, "slide_number": 2, "title": "B", "slide_text": "text"},
            {"id": 3, "slide_number": 3, "title": "C", "slide_text": "text"},
        ]
        active_calls = 0
        max_active_calls = 0

        def fake_generate_text(prompt, **kwargs):
            nonlocal active_calls, max_active_calls
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            time.sleep(0.05)
            active_calls -= 1
            return f"讲解：{prompt}"

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "add_slide_explanation", return_value=1) as add_slide_explanation,
            patch.object(ppt_tutor, "_build_slide_prompt", side_effect=lambda deck, slide, **kwargs: f"slide-{slide['slide_number']}"),
            patch.object(ppt_tutor, "_image_paths_for_generation", return_value=[]),
            patch.object(ppt_tutor, "_is_text_empty", return_value=False),
            patch.object(ppt_tutor, "should_use_lightweight_explanation", return_value=False),
        ):
            ppt_tutor._background_generation_worker(task, {"id": 9, "title": "Deck"}, slides)

        self.assertEqual(max_active_calls, 2)
        self.assertEqual(add_slide_explanation.call_count, 3)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["generated"], 3)

    def test_background_worker_uses_multiple_providers_with_per_provider_limits(self):
        task = {
            "status": "running",
            "progress": 0.0,
            "status_text": "",
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "parallelism": 4,
            "send_image_when_no_text": False,
            "force_image_input": False,
            "provider_pool": [
                {
                    "provider_key": "a",
                    "provider_name": "Provider A",
                    "api_key": "key-a",
                    "active_model": "model-a",
                    "active_model_label": "Provider A / model-a",
                    "supports_image_input": False,
                    "parallel_limit": 1,
                },
                {
                    "provider_key": "b",
                    "provider_name": "Provider B",
                    "api_key": "key-b",
                    "active_model": "model-b",
                    "active_model_label": "Provider B / model-b",
                    "supports_image_input": False,
                    "parallel_limit": 1,
                },
            ],
            "max_tokens": 100,
            "reasoning_depth": "关闭",
            "context_by_slide": {},
            "related_knowledge": "",
            "user_id": 7,
            "stop_requested": False,
            "retry_failed_pages": True,
            "max_retries": 1,
        }
        slides = [
            {"id": 1, "slide_number": 1, "title": "A", "slide_text": "text"},
            {"id": 2, "slide_number": 2, "title": "B", "slide_text": "text"},
            {"id": 3, "slide_number": 3, "title": "C", "slide_text": "text"},
            {"id": 4, "slide_number": 4, "title": "D", "slide_text": "text"},
        ]
        active_by_provider = {"a": 0, "b": 0}
        max_by_provider = {"a": 0, "b": 0}
        used_providers = []

        def fake_generate_text(prompt, **kwargs):
            provider_key = kwargs["provider_key"]
            used_providers.append(provider_key)
            active_by_provider[provider_key] += 1
            max_by_provider[provider_key] = max(max_by_provider[provider_key], active_by_provider[provider_key])
            time.sleep(0.05)
            active_by_provider[provider_key] -= 1
            return f"{provider_key}:{prompt}"

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "add_slide_explanation", return_value=1),
            patch.object(ppt_tutor, "_build_slide_prompt", side_effect=lambda deck, slide, **kwargs: f"slide-{slide['slide_number']}"),
            patch.object(ppt_tutor, "_image_paths_for_generation", return_value=[]),
            patch.object(ppt_tutor, "_is_text_empty", return_value=False),
            patch.object(ppt_tutor, "should_use_lightweight_explanation", return_value=False),
        ):
            ppt_tutor._background_generation_worker(task, {"id": 9, "title": "Deck"}, slides)

        self.assertEqual(set(used_providers), {"a", "b"})
        self.assertLessEqual(max_by_provider["a"], 1)
        self.assertLessEqual(max_by_provider["b"], 1)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["generated"], 4)

    def test_failed_slide_retries_with_another_provider(self):
        task = {
            "status": "running",
            "progress": 0.0,
            "status_text": "",
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "parallelism": 2,
            "send_image_when_no_text": False,
            "force_image_input": False,
            "provider_pool": [
                {
                    "provider_key": "bad",
                    "provider_name": "Bad Provider",
                    "api_key": "bad-key",
                    "active_model": "bad-model",
                    "active_model_label": "Bad Provider / bad-model",
                    "supports_image_input": False,
                    "parallel_limit": 1,
                },
                {
                    "provider_key": "good",
                    "provider_name": "Good Provider",
                    "api_key": "good-key",
                    "active_model": "good-model",
                    "active_model_label": "Good Provider / good-model",
                    "supports_image_input": False,
                    "parallel_limit": 1,
                },
            ],
            "max_tokens": 100,
            "reasoning_depth": "关闭",
            "context_by_slide": {},
            "related_knowledge": "",
            "user_id": 7,
            "stop_requested": False,
            "retry_failed_pages": True,
            "max_retries": 2,
        }
        slide = {"id": 1, "slide_number": 1, "title": "A", "slide_text": "text"}
        provider_attempts = []

        def fake_generate_text(prompt, **kwargs):
            provider_attempts.append(kwargs["provider_key"])
            if kwargs["provider_key"] == "bad":
                raise AIServiceError("temporary failure")
            return "retry succeeded"

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "add_slide_explanation", return_value=1) as add_slide_explanation,
            patch.object(ppt_tutor, "_build_slide_prompt", return_value="slide-1"),
            patch.object(ppt_tutor, "_image_paths_for_generation", return_value=[]),
            patch.object(ppt_tutor, "_is_text_empty", return_value=False),
            patch.object(ppt_tutor, "should_use_lightweight_explanation", return_value=False),
        ):
            ppt_tutor._background_generation_worker(task, {"id": 9, "title": "Deck"}, [slide])

        self.assertEqual(provider_attempts, ["bad", "good"])
        self.assertEqual(add_slide_explanation.call_count, 1)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["generated"], 1)
        self.assertEqual(task["failed"], 0)
        self.assertEqual(task["retried"], 1)

    def test_failed_slide_retries_until_success_within_default_limit(self):
        task = {
            "status": "running",
            "progress": 0.0,
            "status_text": "",
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "parallelism": 1,
            "send_image_when_no_text": False,
            "force_image_input": False,
            "provider_pool": [
                {
                    "provider_key": "flaky",
                    "provider_name": "Flaky Provider",
                    "api_key": "flaky-key",
                    "active_model": "flaky-model",
                    "active_model_label": "Flaky Provider / flaky-model",
                    "supports_image_input": False,
                    "parallel_limit": 1,
                },
            ],
            "max_tokens": 100,
            "reasoning_depth": "关闭",
            "context_by_slide": {},
            "related_knowledge": "",
            "user_id": 7,
            "stop_requested": False,
        }
        slide = {"id": 1, "slide_number": 1, "title": "A", "slide_text": "text"}
        attempts = 0

        def fake_generate_text(prompt, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise AIServiceError("temporary failure")
            return "eventual success"

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "add_slide_explanation", return_value=1) as add_slide_explanation,
            patch.object(ppt_tutor, "_build_slide_prompt", return_value="slide-1"),
            patch.object(ppt_tutor, "_image_paths_for_generation", return_value=[]),
            patch.object(ppt_tutor, "_is_text_empty", return_value=False),
            patch.object(ppt_tutor, "should_use_lightweight_explanation", return_value=False),
        ):
            ppt_tutor._background_generation_worker(task, {"id": 9, "title": "Deck"}, [slide])

        self.assertEqual(attempts, 3)
        self.assertEqual(add_slide_explanation.call_count, 1)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["generated"], 1)
        self.assertEqual(task["failed"], 0)
        self.assertEqual(task["retried"], 2)

    def test_failed_slide_stops_after_max_retry_limit(self):
        task = {
            "status": "running",
            "progress": 0.0,
            "status_text": "",
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "parallelism": 1,
            "send_image_when_no_text": False,
            "force_image_input": False,
            "provider_pool": [
                {
                    "provider_key": "flaky",
                    "provider_name": "Flaky Provider",
                    "api_key": "flaky-key",
                    "active_model": "flaky-model",
                    "active_model_label": "Flaky Provider / flaky-model",
                    "supports_image_input": False,
                    "parallel_limit": 1,
                },
            ],
            "max_tokens": 100,
            "reasoning_depth": "关闭",
            "context_by_slide": {},
            "related_knowledge": "",
            "user_id": 7,
            "stop_requested": False,
            "max_retries": 2,
        }
        slide = {"id": 1, "slide_number": 1, "title": "A", "slide_text": "text"}
        attempts = 0

        def fake_generate_text(prompt, **kwargs):
            nonlocal attempts
            attempts += 1
            raise AIServiceError("temporary failure")

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "add_slide_explanation", return_value=1) as add_slide_explanation,
            patch.object(ppt_tutor, "_build_slide_prompt", return_value="slide-1"),
            patch.object(ppt_tutor, "_image_paths_for_generation", return_value=[]),
            patch.object(ppt_tutor, "_is_text_empty", return_value=False),
            patch.object(ppt_tutor, "should_use_lightweight_explanation", return_value=False),
        ):
            ppt_tutor._background_generation_worker(task, {"id": 9, "title": "Deck"}, [slide])

        self.assertEqual(attempts, 3)
        self.assertEqual(add_slide_explanation.call_count, 0)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["generated"], 0)
        self.assertEqual(task["failed"], 1)
        self.assertEqual(task["retried"], 2)


if __name__ == "__main__":
    unittest.main()
