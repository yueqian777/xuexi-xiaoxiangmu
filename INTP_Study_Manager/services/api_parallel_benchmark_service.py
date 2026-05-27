from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable

import db
from services.ai_service import AIServiceError, generate_text

DEFAULT_PARALLELISM = 8
DEFAULT_START_PARALLELISM = 8
DEFAULT_MAX_PARALLELISM = 64
MIN_SUCCESS_RATE = 0.85
INLINE_BENCHMARK_MIN_SAMPLES = 32
HIGH_ERROR_MIN_SAMPLES = 16
HIGH_ERROR_FAILURE_RATE = 0.30
HIGH_ERROR_RATE_LIMIT_RATE = 0.25
INLINE_RAISE_MIN_SAMPLES = 16
INLINE_RAISE_STEP = 4
BENCHMARK_PROMPT = """
请模拟为一页中文课程 PPT 生成逐页讲解。要求：
1. 用 Markdown 输出，包含“这一页讲什么”“关键点”“怎么理解”三个小节。
2. 如果出现代码或公式，请放在 fenced code block 中。
3. 内容控制在 250 到 400 个汉字，不要只回答 OK。
""".strip()
KEY_PART_SEPARATOR = "\u241f"


def ensure_parallel_benchmark_table() -> None:
    with db.managed_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_parallel_benchmarks (
                benchmark_key TEXT PRIMARY KEY,
                provider_key TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                api_key_fingerprint TEXT NOT NULL DEFAULT '',
                parallel_limit INTEGER NOT NULL DEFAULT 0,
                success_rate REAL NOT NULL DEFAULT 0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                rate_limit_count INTEGER NOT NULL DEFAULT 0,
                timeout_count INTEGER NOT NULL DEFAULT 0,
                probe_json TEXT NOT NULL DEFAULT '{}',
                is_authoritative INTEGER NOT NULL DEFAULT 0,
                invalidated_at TEXT DEFAULT '',
                invalidated_reason TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_parallel_benchmarks_provider
            ON api_parallel_benchmarks(provider_key, model, base_url, api_key_fingerprint)
            """
        )


def api_key_fingerprint(api_key: str | None) -> str:
    key = str(api_key or "").strip()
    if not key:
        return "empty"
    payload = f"intp-study-manager-api-key:{key}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def provider_api_key_for_fingerprint(provider: dict[str, Any]) -> str:
    key = str(provider.get("api_key") or "").strip()
    if key:
        return key
    env_name = str(provider.get("api_key_env") or "").strip()
    if env_name:
        key = str(os.getenv(env_name) or "").strip()
        if key:
            return key
    auth_type = str(provider.get("auth_type") or "").strip()
    if auth_type == "none":
        return "auth:none"
    provider_name = str(provider.get("name") or provider.get("provider_name") or "").lower()
    base_url = str(provider.get("base_url") or "").lower()
    if "cliproxy" in provider_name or "localhost" in base_url or "127.0.0.1" in base_url:
        return "implicit-local-client-key"
    return ""


def benchmark_key(provider: dict[str, Any]) -> str:
    provider_key = str(provider.get("provider_key") or "").strip()
    model = str(provider.get("active_model") or provider.get("model") or "").strip()
    base_url = str(provider.get("base_url") or "").strip().rstrip("/")
    key_fingerprint = api_key_fingerprint(provider_api_key_for_fingerprint(provider))
    return KEY_PART_SEPARATOR.join([provider_key, model, base_url, key_fingerprint])


def load_benchmark_result(provider: dict[str, Any], *, authoritative_only: bool = True) -> dict[str, Any] | None:
    ensure_parallel_benchmark_table()
    query = "SELECT * FROM api_parallel_benchmarks WHERE benchmark_key = ?"
    params: list[Any] = [benchmark_key(provider)]
    if authoritative_only:
        query += " AND is_authoritative = 1 AND COALESCE(invalidated_at, '') = ''"
    row = db.fetch_one(query, params)
    if not row:
        return None
    return _row_to_result(row)


def load_benchmark_results(
    providers: list[dict[str, Any]],
    *,
    authoritative_only: bool = True,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for provider in providers:
        result = load_benchmark_result(provider, authoritative_only=authoritative_only)
        if result:
            results[benchmark_key(provider)] = result
    return results


def save_benchmark_result(result: dict[str, Any]) -> None:
    ensure_parallel_benchmark_table()
    key = str(result.get("benchmark_key") or benchmark_key(result))
    is_authoritative = bool(result.get("is_authoritative"))
    existing = db.fetch_one("SELECT * FROM api_parallel_benchmarks WHERE benchmark_key = ?", (key,))
    if existing and int(existing.get("is_authoritative") or 0) and not is_authoritative:
        merged = _merge_partial_probe_json(existing, result)
        db.execute(
            """
            UPDATE api_parallel_benchmarks
            SET probe_json = ?, updated_at = datetime('now', 'localtime')
            WHERE benchmark_key = ?
            """,
            (json.dumps(merged, ensure_ascii=False), key),
        )
        return

    probe_json = json.dumps(_safe_probe_payload(result), ensure_ascii=False)
    db.execute(
        """
        INSERT INTO api_parallel_benchmarks (
            benchmark_key,
            provider_key,
            model,
            base_url,
            api_key_fingerprint,
            parallel_limit,
            success_rate,
            sample_count,
            failure_count,
            rate_limit_count,
            timeout_count,
            probe_json,
            is_authoritative,
            invalidated_at,
            invalidated_reason,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(benchmark_key) DO UPDATE SET
            provider_key = excluded.provider_key,
            model = excluded.model,
            base_url = excluded.base_url,
            api_key_fingerprint = excluded.api_key_fingerprint,
            parallel_limit = excluded.parallel_limit,
            success_rate = excluded.success_rate,
            sample_count = excluded.sample_count,
            failure_count = excluded.failure_count,
            rate_limit_count = excluded.rate_limit_count,
            timeout_count = excluded.timeout_count,
            probe_json = excluded.probe_json,
            is_authoritative = excluded.is_authoritative,
            invalidated_at = excluded.invalidated_at,
            invalidated_reason = excluded.invalidated_reason,
            updated_at = excluded.updated_at
        """,
        (
            key,
            str(result.get("provider_key") or ""),
            str(result.get("model") or result.get("active_model") or ""),
            str(result.get("base_url") or "").rstrip("/"),
            str(result.get("api_key_fingerprint") or api_key_fingerprint(provider_api_key_for_fingerprint(result))),
            int(result.get("parallel_limit") or 0),
            float(result.get("success_rate") or 0.0),
            int(result.get("sample_count") or 0),
            int(result.get("failure_count") or 0),
            int(result.get("rate_limit_count") or 0),
            int(result.get("timeout_count") or 0),
            probe_json,
            1 if is_authoritative else 0,
            str(result.get("invalidated_at") or ""),
            str(result.get("invalidated_reason") or ""),
        ),
    )


def mark_benchmark_invalidated(provider: dict[str, Any], reason: str) -> None:
    ensure_parallel_benchmark_table()
    db.execute(
        """
        UPDATE api_parallel_benchmarks
        SET is_authoritative = 0,
            invalidated_at = ?,
            invalidated_reason = ?,
            updated_at = datetime('now', 'localtime')
        WHERE benchmark_key = ?
        """,
        (_now_text(), reason, benchmark_key(provider)),
    )


def probe_provider_parallel_limit(
    provider: dict[str, Any],
    *,
    start_parallelism: int = DEFAULT_START_PARALLELISM,
    max_parallelism: int = DEFAULT_MAX_PARALLELISM,
    request_func: Callable[..., str] = generate_text,
    previous_result: dict[str, Any] | None = None,
    min_success_rate: float = MIN_SUCCESS_RATE,
) -> dict[str, Any]:
    max_parallelism = _positive_int(max_parallelism, DEFAULT_MAX_PARALLELISM)
    start_parallelism = _positive_int(start_parallelism, DEFAULT_START_PARALLELISM)
    start_parallelism = min(max_parallelism, max(1, _start_from_previous(previous_result, start_parallelism, max_parallelism)))

    probes: list[dict[str, Any]] = []
    best_probe: dict[str, Any] | None = None

    for concurrency in _upward_candidates(start_parallelism, max_parallelism):
        probe = run_provider_parallel_probe(
            provider,
            concurrency,
            request_func=request_func,
            min_success_rate=min_success_rate,
        )
        probes.append(probe)
        if probe["success_rate"] >= min_success_rate:
            best_probe = probe
            continue
        break

    if best_probe is None:
        for concurrency in _downward_candidates(start_parallelism):
            if concurrency > max_parallelism:
                continue
            probe = run_provider_parallel_probe(
                provider,
                concurrency,
                request_func=request_func,
                min_success_rate=min_success_rate,
            )
            probes.append(probe)
            if probe["success_rate"] >= min_success_rate:
                best_probe = probe
                break

    if best_probe:
        parallel_limit = int(best_probe["concurrency"])
        sample_count = int(best_probe["sample_count"])
        failure_count = int(best_probe["failure_count"])
        rate_limit_count = int(best_probe["rate_limit_count"])
        timeout_count = int(best_probe["timeout_count"])
        success_rate = float(best_probe["success_rate"])
    else:
        parallel_limit = 0
        sample_count = sum(int(probe.get("sample_count") or 0) for probe in probes)
        failure_count = sum(int(probe.get("failure_count") or 0) for probe in probes)
        rate_limit_count = sum(int(probe.get("rate_limit_count") or 0) for probe in probes)
        timeout_count = sum(int(probe.get("timeout_count") or 0) for probe in probes)
        success_rate = 0.0

    result = _provider_identity(provider)
    result.update(
        {
            "benchmark_key": benchmark_key(provider),
            "parallel_limit": parallel_limit,
            "success_rate": success_rate,
            "sample_count": sample_count,
            "failure_count": failure_count,
            "rate_limit_count": rate_limit_count,
            "timeout_count": timeout_count,
            "probes": probes,
            "ok": parallel_limit > 0 and success_rate >= min_success_rate,
            "is_authoritative": parallel_limit > 0 and success_rate >= min_success_rate,
            "measured_at": time.time(),
        }
    )
    return result


def benchmark_provider_pool(
    provider_pool: list[dict[str, Any]],
    *,
    start_parallelism: int = DEFAULT_START_PARALLELISM,
    max_parallelism: int = DEFAULT_MAX_PARALLELISM,
    request_func: Callable[..., str] = generate_text,
) -> dict[str, Any]:
    provider_results = []
    for provider in provider_pool:
        previous_result = load_benchmark_result(provider, authoritative_only=False)
        provider_results.append(
            probe_provider_parallel_limit(
                provider,
                start_parallelism=start_parallelism,
                max_parallelism=max_parallelism,
                request_func=request_func,
                previous_result=previous_result,
            )
        )
    return {
        "providers": provider_results,
        "group_parallel_limit": sum(int(item.get("parallel_limit") or 0) for item in provider_results),
        "measured_at": time.time(),
    }


def run_provider_parallel_probe(
    provider: dict[str, Any],
    concurrency: int,
    *,
    request_func: Callable[..., str] = generate_text,
    min_success_rate: float = MIN_SUCCESS_RATE,
) -> dict[str, Any]:
    concurrency = max(1, int(concurrency))
    sample_count = max(DEFAULT_START_PARALLELISM, concurrency)

    def request_once(_: int) -> dict[str, Any]:
        started_at = time.monotonic()
        try:
            request_func(
                BENCHMARK_PROMPT,
                provider_key=provider.get("provider_key"),
                api_key=provider.get("api_key"),
                model_override=provider.get("active_model") or provider.get("model"),
                max_output_tokens=800,
            )
            return {"ok": True, "latency": time.monotonic() - started_at}
        except Exception as exc:
            return {
                "ok": False,
                "latency": time.monotonic() - started_at,
                "category": classify_error_category(exc),
                "message": str(exc),
            }

    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(executor.map(request_once, range(sample_count)))
    elapsed = time.monotonic() - started_at
    successes = sum(1 for result in results if result.get("ok"))
    failures = sample_count - successes
    categories = [str(result.get("category") or "") for result in results if not result.get("ok")]
    success_rate = successes / sample_count if sample_count else 0.0
    messages = [str(result.get("message") or "") for result in results if not result.get("ok")]
    return {
        "concurrency": concurrency,
        "ok": success_rate >= min_success_rate,
        "successes": successes,
        "failures": failures,
        "sample_count": sample_count,
        "success_rate": round(success_rate, 4),
        "failure_count": failures,
        "rate_limit_count": categories.count("rate_limit"),
        "timeout_count": categories.count("timeout"),
        "elapsed": elapsed,
        "message": messages[0] if messages else "",
        "category": categories[0] if categories else "",
    }


def new_generation_benchmark_stats(provider_pool: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for provider in provider_pool:
        key = benchmark_key(provider)
        identity = _provider_identity(provider)
        identity.update(
            {
                "benchmark_key": key,
                "configured_parallel_limit": _positive_int(provider.get("parallel_limit"), DEFAULT_PARALLELISM),
                "observed_parallel_limit": 0,
                "sample_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "rate_limit_count": 0,
                "timeout_count": 0,
                "degraded": False,
                "degraded_from": 0,
                "degraded_to": 0,
                "raised_to": 0,
                "last_raise_sample": 0,
            }
        )
        stats[key] = identity
    return stats


def record_generation_schedule(
    stats: dict[str, dict[str, Any]],
    provider: dict[str, Any],
    running_count: int,
) -> None:
    item = stats.get(benchmark_key(provider))
    if not item:
        return
    item["observed_parallel_limit"] = max(int(item.get("observed_parallel_limit") or 0), int(running_count or 0))


def record_generation_outcome(
    stats: dict[str, dict[str, Any]],
    provider: dict[str, Any],
    *,
    status: str,
    error_category: str | None = None,
) -> None:
    item = stats.get(benchmark_key(provider))
    if not item:
        return
    if status == "skipped":
        return
    item["sample_count"] = int(item.get("sample_count") or 0) + 1
    if status == "generated":
        item["success_count"] = int(item.get("success_count") or 0) + 1
        return
    item["failure_count"] = int(item.get("failure_count") or 0) + 1
    category = str(error_category or "unknown")
    if category == "rate_limit":
        item["rate_limit_count"] = int(item.get("rate_limit_count") or 0) + 1
    if category == "timeout":
        item["timeout_count"] = int(item.get("timeout_count") or 0) + 1


def maybe_degrade_provider_parallel_limit(
    provider_state: dict[str, Any],
    stats: dict[str, dict[str, Any]],
    *,
    min_samples: int = HIGH_ERROR_MIN_SAMPLES,
    failure_rate_threshold: float = HIGH_ERROR_FAILURE_RATE,
    rate_limit_rate_threshold: float = HIGH_ERROR_RATE_LIMIT_RATE,
) -> bool:
    provider = provider_state.get("provider") or {}
    item = stats.get(benchmark_key(provider))
    if not item or item.get("degraded"):
        return False
    sample_count = int(item.get("sample_count") or 0)
    if sample_count < min_samples:
        return False
    failure_rate = int(item.get("failure_count") or 0) / sample_count
    rate_limit_rate = int(item.get("rate_limit_count") or 0) / sample_count
    if failure_rate < failure_rate_threshold and rate_limit_rate < rate_limit_rate_threshold:
        return False
    current_limit = max(1, int(provider_state.get("parallel_limit") or 1))
    new_limit = max(1, int(current_limit * 0.75))
    if new_limit >= current_limit and current_limit > 1:
        new_limit = current_limit - 1
    if new_limit == current_limit:
        return False
    provider_state["parallel_limit"] = new_limit
    item["degraded"] = True
    item["degraded_from"] = current_limit
    item["degraded_to"] = new_limit
    return True


def maybe_raise_provider_parallel_limit(
    provider_state: dict[str, Any],
    stats: dict[str, dict[str, Any]],
    *,
    total_targets: int,
    min_samples: int = INLINE_RAISE_MIN_SAMPLES,
    min_success_rate: float = MIN_SUCCESS_RATE,
    raise_step: int = INLINE_RAISE_STEP,
) -> bool:
    provider = provider_state.get("provider") or {}
    item = stats.get(benchmark_key(provider))
    if not item or item.get("degraded"):
        return False
    sample_count = int(item.get("sample_count") or 0)
    if sample_count < min_samples:
        return False
    last_raise_sample = int(item.get("last_raise_sample") or 0)
    if sample_count - last_raise_sample < min_samples:
        return False
    success_count = int(item.get("success_count") or 0)
    success_rate = success_count / sample_count if sample_count else 0.0
    if success_rate < min_success_rate:
        return False
    current_limit = max(1, int(provider_state.get("parallel_limit") or 1))
    target_limit = max(current_limit, int(total_targets or current_limit))
    new_limit = min(target_limit, current_limit + max(1, int(raise_step)))
    if new_limit <= current_limit:
        return False
    provider_state["parallel_limit"] = new_limit
    item["last_raise_sample"] = sample_count
    item["raised_to"] = new_limit
    return True


def finalize_generation_benchmark_stats(
    stats: dict[str, dict[str, Any]],
    *,
    min_samples: int = INLINE_BENCHMARK_MIN_SAMPLES,
    min_success_rate: float = MIN_SUCCESS_RATE,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in stats.values():
        sample_count = int(item.get("sample_count") or 0)
        success_count = int(item.get("success_count") or 0)
        success_rate = round(success_count / sample_count, 4) if sample_count else 0.0
        parallel_limit = max(
            int(item.get("observed_parallel_limit") or 0),
            int(item.get("configured_parallel_limit") or 0),
        )
        is_authoritative = sample_count >= min_samples and success_rate >= min_success_rate and not bool(item.get("degraded"))
        result = dict(item)
        result.update(
            {
                "parallel_limit": parallel_limit if is_authoritative else 0,
                "success_rate": success_rate,
                "sample_count": sample_count,
                "failure_count": int(item.get("failure_count") or 0),
                "rate_limit_count": int(item.get("rate_limit_count") or 0),
                "timeout_count": int(item.get("timeout_count") or 0),
                "is_authoritative": is_authoritative,
                "probes": [
                    {
                        "source": "ppt_generation",
                        "sample_count": sample_count,
                        "success_rate": success_rate,
                        "observed_parallel_limit": int(item.get("observed_parallel_limit") or 0),
                        "configured_parallel_limit": int(item.get("configured_parallel_limit") or 0),
                    }
                ],
            }
        )
        results.append(result)
    return results


def _provider_identity(provider: dict[str, Any]) -> dict[str, Any]:
    model = str(provider.get("active_model") or provider.get("model") or "").strip()
    base_url = str(provider.get("base_url") or "").strip().rstrip("/")
    return {
        "provider_key": str(provider.get("provider_key") or "").strip(),
        "provider_name": str(provider.get("provider_name") or provider.get("name") or "").strip(),
        "model": model,
        "active_model": model,
        "base_url": base_url,
        "api_key_fingerprint": api_key_fingerprint(provider_api_key_for_fingerprint(provider)),
    }


def _row_to_result(row: dict[str, Any]) -> dict[str, Any]:
    probe_json = _parse_json_object(row.get("probe_json") or "{}")
    result = dict(probe_json)
    result.update(
        {
            "benchmark_key": row.get("benchmark_key"),
            "provider_key": row.get("provider_key"),
            "model": row.get("model") or "",
            "active_model": row.get("model") or "",
            "base_url": row.get("base_url") or "",
            "api_key_fingerprint": row.get("api_key_fingerprint") or "",
            "parallel_limit": int(row.get("parallel_limit") or 0),
            "success_rate": float(row.get("success_rate") or 0.0),
            "sample_count": int(row.get("sample_count") or 0),
            "failure_count": int(row.get("failure_count") or 0),
            "rate_limit_count": int(row.get("rate_limit_count") or 0),
            "timeout_count": int(row.get("timeout_count") or 0),
            "is_authoritative": bool(row.get("is_authoritative")),
            "invalidated_at": row.get("invalidated_at") or "",
            "invalidated_reason": row.get("invalidated_reason") or "",
            "updated_at": row.get("updated_at") or "",
        }
    )
    return result


def _safe_probe_payload(result: dict[str, Any]) -> dict[str, Any]:
    safe = {
        "provider_name": result.get("provider_name") or "",
        "probes": result.get("probes") or [],
        "configured_parallel_limit": result.get("configured_parallel_limit") or 0,
        "observed_parallel_limit": result.get("observed_parallel_limit") or 0,
        "degraded": bool(result.get("degraded")),
        "degraded_from": int(result.get("degraded_from") or 0),
        "degraded_to": int(result.get("degraded_to") or 0),
        "measured_at": result.get("measured_at") or time.time(),
    }
    return _strip_sensitive(safe)


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_sensitive(item)
            for key, item in value.items()
            if str(key).lower() not in {"api_key", "authorization", "x-api-key"}
        }
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    return value


def _merge_partial_probe_json(existing: dict[str, Any], partial_result: dict[str, Any]) -> dict[str, Any]:
    current = _parse_json_object(existing.get("probe_json") or "{}")
    partial = _safe_probe_payload(partial_result)
    current.setdefault("partial_runs", []).append(partial)
    return _strip_sensitive(current)


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _positive_int(value: Any, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def classify_error_category(exc: Exception) -> str:
    category = str(getattr(exc, "category", "") or "")
    if category:
        return category
    message = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in message or "timed out" in message:
        return "timeout"
    if "rate limit" in message or "too many requests" in message or "429" in message:
        return "rate_limit"
    return "unknown"


def _upward_candidates(start: int, maximum: int) -> list[int]:
    candidates = [max(1, min(start, maximum))]
    while candidates[-1] < maximum:
        current = candidates[-1]
        if current < 16:
            next_value = current + 4
        elif current < 32:
            next_value = current + 8
        else:
            next_value = current + 16
        next_value = min(maximum, next_value)
        if next_value <= current:
            break
        candidates.append(next_value)
    return candidates


def _downward_candidates(start: int) -> list[int]:
    return [candidate for candidate in (6, 4, 2, 1) if candidate < start]


def _start_from_previous(previous_result: dict[str, Any] | None, default_start: int, maximum: int) -> int:
    if not previous_result:
        return default_start
    try:
        previous_limit = int(previous_result.get("parallel_limit") or 0)
    except (TypeError, ValueError):
        previous_limit = 0
    if previous_limit > 0:
        return min(maximum, max(default_start, previous_limit))
    probes = previous_result.get("probes")
    if not isinstance(probes, list):
        return default_start
    accepted = [
        int(probe.get("concurrency") or 0)
        for probe in probes
        if float(probe.get("success_rate") or 0.0) >= MIN_SUCCESS_RATE
    ]
    if accepted:
        return min(maximum, max(default_start, max(accepted)))
    failed = [int(probe.get("concurrency") or 0) for probe in probes if int(probe.get("concurrency") or 0) > 0]
    if failed:
        return max(1, min(default_start, min(failed)))
    return default_start


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")
