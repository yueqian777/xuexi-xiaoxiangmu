import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services.ai_service import AIServiceError
from services import api_parallel_benchmark_service as benchmark


class ApiParallelBenchmarkServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.db_patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
        ]
        for patcher in self.db_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        benchmark.ensure_parallel_benchmark_table()

    def _provider(self, api_key="sk-test-a", model="model-a"):
        return {
            "provider_key": "provider-a",
            "provider_name": "Provider A",
            "name": "Provider A",
            "base_url": "https://api.example.com/v1/",
            "model": model,
            "active_model": model,
            "api_key": api_key,
            "api_key_env": "",
            "auth_type": "bearer",
        }

    def test_fingerprint_is_stable_without_exposing_raw_key(self):
        first = benchmark.api_key_fingerprint("sk-secret-value")
        second = benchmark.api_key_fingerprint(" sk-secret-value ")

        self.assertEqual(first, second)
        self.assertNotEqual(first, benchmark.api_key_fingerprint("sk-other-value"))
        self.assertNotIn("sk-secret-value", first)

    def test_benchmark_key_is_bound_to_api_key_model_and_base_url(self):
        provider_a = self._provider(api_key="sk-a", model="model-a")
        provider_b = self._provider(api_key="sk-b", model="model-a")
        provider_c = self._provider(api_key="sk-a", model="model-b")

        self.assertNotEqual(benchmark.benchmark_key(provider_a), benchmark.benchmark_key(provider_b))
        self.assertNotEqual(benchmark.benchmark_key(provider_a), benchmark.benchmark_key(provider_c))

    def test_probe_starts_at_eight_and_accepts_success_rate_above_85_percent(self):
        calls = []
        active = 0

        def fake_request(prompt, **kwargs):
            nonlocal active
            active += 1
            calls.append((kwargs["provider_key"], active))
            try:
                if active > 8:
                    raise AIServiceError("rate limit", category="rate_limit")
                time.sleep(0.01)
                return "ok"
            finally:
                active -= 1

        result = benchmark.probe_provider_parallel_limit(
            self._provider(),
            start_parallelism=8,
            max_parallelism=12,
            request_func=fake_request,
        )

        self.assertEqual(result["probes"][0]["concurrency"], 8)
        self.assertEqual(result["parallel_limit"], 8)
        self.assertGreaterEqual(result["success_rate"], 0.85)
        self.assertTrue(result["is_authoritative"])

    def test_probe_drops_to_six_when_eight_is_too_high(self):
        active = 0

        def fake_request(prompt, **kwargs):
            nonlocal active
            active += 1
            try:
                if active > 6:
                    raise AIServiceError("rate limit", category="rate_limit")
                time.sleep(0.01)
                return "ok"
            finally:
                active -= 1

        result = benchmark.probe_provider_parallel_limit(
            self._provider(),
            start_parallelism=8,
            max_parallelism=12,
            request_func=fake_request,
        )

        self.assertEqual([probe["concurrency"] for probe in result["probes"][:2]], [8, 6])
        self.assertEqual(result["parallel_limit"], 6)

    def test_authoritative_result_is_persisted_and_loaded_for_same_key_only(self):
        result = benchmark.probe_provider_parallel_limit(
            self._provider(api_key="sk-a"),
            start_parallelism=8,
            max_parallelism=8,
            request_func=lambda prompt, **kwargs: "ok",
        )

        benchmark.save_benchmark_result(result)

        loaded_same = benchmark.load_benchmark_result(self._provider(api_key="sk-a"))
        loaded_other = benchmark.load_benchmark_result(self._provider(api_key="sk-b"))
        self.assertIsNotNone(loaded_same)
        self.assertEqual(loaded_same["parallel_limit"], 8)
        self.assertIsNone(loaded_other)

    def test_saved_probe_payload_does_not_store_raw_api_key(self):
        result = benchmark.probe_provider_parallel_limit(
            self._provider(api_key="sk-secret-raw"),
            start_parallelism=8,
            max_parallelism=8,
            request_func=lambda prompt, **kwargs: "ok",
        )

        benchmark.save_benchmark_result(result)
        row = db.fetch_one("SELECT * FROM api_parallel_benchmarks WHERE benchmark_key = ?", (result["benchmark_key"],))

        self.assertIsNotNone(row)
        self.assertNotIn("sk-secret-raw", row["benchmark_key"])
        self.assertNotIn("sk-secret-raw", row["api_key_fingerprint"])
        self.assertNotIn("sk-secret-raw", row["probe_json"])

    def test_inline_stats_need_enough_samples_before_authoritative_save(self):
        provider = self._provider()
        low_sample_stats = benchmark.new_generation_benchmark_stats([provider])
        for _ in range(24):
            benchmark.record_generation_outcome(low_sample_stats, provider, status="generated")

        low_sample_result = benchmark.finalize_generation_benchmark_stats(
            low_sample_stats,
            min_samples=32,
        )[0]
        benchmark.save_benchmark_result(low_sample_result)
        self.assertFalse(low_sample_result["is_authoritative"])
        self.assertIsNone(benchmark.load_benchmark_result(provider))

        enough_stats = benchmark.new_generation_benchmark_stats([provider])
        for index in range(40):
            status = "generated" if index < 36 else "failed"
            benchmark.record_generation_outcome(enough_stats, provider, status=status)

        enough_result = benchmark.finalize_generation_benchmark_stats(
            enough_stats,
            min_samples=32,
        )[0]
        benchmark.save_benchmark_result(enough_result)
        loaded = benchmark.load_benchmark_result(provider)

        self.assertTrue(enough_result["is_authoritative"])
        self.assertEqual(enough_result["success_rate"], 0.9)
        self.assertIsNotNone(loaded)

    def test_high_error_rate_degrades_limit_but_isolated_errors_do_not(self):
        provider = self._provider()
        provider_state = {"provider": provider, "parallel_limit": 16}
        stats = benchmark.new_generation_benchmark_stats([provider])

        for _ in range(11):
            benchmark.record_generation_outcome(stats, provider, status="generated")
        benchmark.record_generation_outcome(stats, provider, status="failed", error_category="rate_limit")
        self.assertFalse(benchmark.maybe_degrade_provider_parallel_limit(provider_state, stats))
        self.assertEqual(provider_state["parallel_limit"], 16)

        for _ in range(5):
            benchmark.record_generation_outcome(stats, provider, status="failed", error_category="rate_limit")
        self.assertTrue(benchmark.maybe_degrade_provider_parallel_limit(provider_state, stats))
        self.assertLess(provider_state["parallel_limit"], 16)
        self.assertTrue(stats[benchmark.benchmark_key(provider)]["degraded"])

    def test_inline_generation_can_raise_limit_after_stable_samples(self):
        provider = self._provider()
        provider_state = {"provider": provider, "parallel_limit": 8}
        stats = benchmark.new_generation_benchmark_stats([provider])

        for _ in range(15):
            benchmark.record_generation_outcome(stats, provider, status="generated")
        self.assertFalse(benchmark.maybe_raise_provider_parallel_limit(provider_state, stats, total_targets=40))
        self.assertEqual(provider_state["parallel_limit"], 8)

        benchmark.record_generation_outcome(stats, provider, status="generated")
        self.assertTrue(benchmark.maybe_raise_provider_parallel_limit(provider_state, stats, total_targets=40))
        self.assertEqual(provider_state["parallel_limit"], 12)


if __name__ == "__main__":
    unittest.main()
