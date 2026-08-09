from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


TASK_PACKAGE_TYPE = "intp_chatgpt_explanation_task"
RESULT_PACKAGE_TYPE = "intp_chatgpt_explanation_result"
SCHEMA_VERSION = "1.0"
TASK_SCHEMA_VERSION = SCHEMA_VERSION
RESULT_SCHEMA_VERSION = SCHEMA_VERSION
TASK_PACKAGE_VERSION = TASK_SCHEMA_VERSION
RESULT_PACKAGE_VERSION = RESULT_SCHEMA_VERSION
PRIVACY_MODE = "ppt_explanation_task_only"
TASK_PRIVACY_MODE = PRIVACY_MODE
CHATGPT_WEB_GENERATOR = "chatgpt_web"
GENERATOR = CHATGPT_WEB_GENERATOR
RESULT_FILENAME = "explanation_result.json"

# A result contains plain UTF-8 JSON only.  Five MiB leaves ample room for a
# multi-slide Markdown explanation while bounding inbox memory use.
MAX_RESULT_BYTES = 5 * 1024 * 1024
MAX_EXPLANATION_CHARS = 100_000
MAX_RESULT_SLIDES = 100

DEFAULT_MAX_SLIDES_PER_TASK = 20
MAX_SLIDES_PER_TASK = 25
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
SUPPORTED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})

TASK_STATUSES = frozenset(
    {"created", "waiting_result", "result_detected", "imported", "partial", "failed"}
)
RESULT_STATUSES = frozenset({"detected", "imported", "partial", "failed", "skipped"})

TASK_MANIFEST_REQUIRED_FIELDS = frozenset(
    {
        "package_type",
        "version",
        "task_id",
        "user_id",
        "deck_id",
        "deck_fingerprint",
        "subject",
        "deck_title",
        "created_at",
        "requested_slide_count",
        "requested_slides",
        "result_schema_version",
        "privacy_mode",
    }
)
RESULT_REQUIRED_FIELDS = frozenset(
    {
        "package_type",
        "version",
        "result_id",
        "task_id",
        "deck_id",
        "deck_fingerprint",
        "generator",
        "generated_at",
        "slides",
    }
)
RESULT_SLIDE_REQUIRED_FIELDS = frozenset({"slide_id", "slide_number", "explanation"})

# Task payloads are assembled from these explicit allowlists.  New database
# fields therefore never become public merely because a SELECT * gains a column.
TASK_MANIFEST_ALLOWLIST = TASK_MANIFEST_REQUIRED_FIELDS
SLIDE_PAYLOAD_ALLOWLIST = frozenset(
    {
        "slide_id",
        "slide_number",
        "title",
        "slide_text",
        "section_index",
        "section_title",
        "section_summary",
        "page_type",
        "slide_role",
        "key_points",
        "image_path",
        "existing_explanation",
    }
)
SECTION_PAYLOAD_ALLOWLIST = frozenset(
    {
        "section_index",
        "title",
        "topic",
        "core_question",
        "summary",
        "key_terms",
        "prerequisite_concepts",
        "start_slide",
        "end_slide",
    }
)


class DuplicateJsonKeyError(ValueError):
    """Raised when an object contains a duplicate JSON member name."""


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"JSON 包含重复字段：{key}")
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise ValueError(f"JSON 包含无效数值：{value}")


def strict_json_loads(text: str, *, require_object: bool = True) -> dict[str, Any] | Any:
    """Parse JSON without accepting duplicate keys or a non-object root."""

    if not isinstance(text, str):
        raise ValueError("JSON 内容必须是文本")
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_number,
        )
    except DuplicateJsonKeyError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误：{exc.msg}") from exc
    except RecursionError as exc:
        raise ValueError("JSON 嵌套层级过深") from exc
    if require_object and not isinstance(payload, dict):
        raise ValueError("JSON 顶层必须是对象")
    return payload


def load_json_bytes(
    data: bytes | bytearray | memoryview,
    *,
    max_bytes: int = MAX_RESULT_BYTES,
    require_object: bool = True,
) -> dict[str, Any] | Any:
    """Decode and parse a size-bounded UTF-8 JSON document."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("JSON 文件内容必须是字节数据")
    raw = bytes(data)
    if len(raw) > int(max_bytes):
        raise ValueError(f"JSON 文件过大（最大 {int(max_bytes)} 字节）")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("JSON 文件必须使用 UTF-8 编码") from exc
    return strict_json_loads(text, require_object=require_object)


def load_json_file(
    path: str | Path,
    *,
    max_bytes: int = MAX_RESULT_BYTES,
    require_object: bool = True,
) -> dict[str, Any] | Any:
    """Read a regular file and pass it through the strict JSON loader."""

    source = Path(path)
    if not source.is_file():
        raise ValueError("JSON 文件不存在")
    if source.stat().st_size > int(max_bytes):
        raise ValueError(f"JSON 文件过大（最大 {int(max_bytes)} 字节）")
    return load_json_bytes(
        source.read_bytes(),
        max_bytes=max_bytes,
        require_object=require_object,
    )


# Descriptive aliases keep callers readable without introducing alternate
# parsing behavior.
parse_json_bytes = load_json_bytes
read_json_file = load_json_file
