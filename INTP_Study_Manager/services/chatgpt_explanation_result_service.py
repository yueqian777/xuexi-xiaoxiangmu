from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import db
from services import chatgpt_explanation_schema as schema
from services import chatgpt_explanation_task_service as task_service
from services import slide_explanation_write_service as explanation_writer


MODEL_NAME = "ChatGPT Web"
_TOP_LEVEL_FIELDS = schema.RESULT_REQUIRED_FIELDS
_SLIDE_FIELDS = schema.RESULT_SLIDE_REQUIRED_FIELDS
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def preview_result(user_id: int, result_source: Any) -> dict[str, Any]:
    """Parse and validate a ChatGPT Web result without changing the database."""
    report = _empty_report()
    try:
        user_id_int = _user_id(user_id)
        raw = _read_result_bytes(result_source)
        payload = schema.load_json_bytes(raw)
    except Exception as exc:
        report["errors"].append(_input_error(exc))
        return _finalize_report(report)

    db.init_db()
    conn = db.get_connection()
    try:
        return _validate_payload(conn, user_id_int, payload)
    except Exception:
        report = _empty_report(payload)
        report["errors"].append("结果校验失败：无法读取当前数据库状态。")
        return _finalize_report(report)
    finally:
        conn.close()


def import_result(
    user_id: int,
    result_source: Any,
    *,
    allow_partial: bool = False,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Append validated explanations atomically and record result provenance."""
    user_id_int = _user_id(user_id)
    try:
        raw = _read_result_bytes(result_source)
    except Exception as exc:
        raise ValueError(_input_error(exc)) from exc

    provenance_path = _source_path(result_source, source_path)
    db.init_db()
    with db.write_transaction() as conn:
        try:
            payload = schema.load_json_bytes(raw)
        except Exception as exc:
            raise ValueError(_input_error(exc)) from exc

        # The complete schema, ownership, fingerprint, and slide mapping checks are
        # deliberately repeated while holding the same write transaction as INSERTs.
        raw_result_json = raw.decode("utf-8")
        report = _validate_payload(conn, user_id_int, payload)
        if not report["hard_valid"]:
            raise ValueError("结果校验失败：" + "；".join(report["errors"]))
        if report["duplicate"]:
            return _skipped_outcome(report)
        if not report["complete"] and not allow_partial:
            raise ValueError(
                f"这是部分结果（{report['valid_count']} / {report['requested_count']} 页），"
                "需要明确允许部分导入。"
            )
        if report["valid_count"] <= 0:
            raise ValueError("部分结果中没有可导入的有效页面。")

        result_status = "imported" if report["complete"] else "partial"
        now = datetime.now().isoformat(timespec="seconds")
        try:
            conn.execute(
                """
                INSERT INTO chatgpt_explanation_results (
                    user_id, result_id, task_id, source_path, slide_count,
                    status, raw_result_json, imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id_int,
                    report["result_id"],
                    report["task_id"],
                    provenance_path,
                    report["valid_count"],
                    result_status,
                    raw_result_json,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing_result = _existing_result(conn, user_id_int, report["result_id"])
            if existing_result is not None:
                if not _payload_matches_stored(existing_result, payload):
                    raise ValueError(
                        "result_id 已存在，但结果内容与首次导入记录不一致，拒绝复用。"
                    ) from exc
                report["duplicate"] = True
                report["already_imported"] = True
                report["auto_import_allowed"] = False
                report["duplicate_payload_matches"] = True
                report["existing_source_path"] = str(
                    existing_result["source_path"] or ""
                )
                return _skipped_outcome(report)
            raise exc

        explanation_writer.append_slide_explanations(
            user_id_int,
            report["valid_slides"],
            model=MODEL_NAME,
            deck_id=report["deck_id"],
            expected_deck_fingerprint=str(payload["deck_fingerprint"]),
            max_items=schema.MAX_RESULT_SLIDES,
            conn=conn,
        )

        if result_status == "imported":
            conn.execute(
                """
                UPDATE chatgpt_explanation_tasks
                SET status = 'imported', completed_at = ?
                WHERE user_id = ? AND task_id = ?
                """,
                (now, user_id_int, report["task_id"]),
            )
        else:
            # A later partial regeneration must not downgrade a task that has
            # already received a complete result.
            conn.execute(
                """
                UPDATE chatgpt_explanation_tasks
                SET status = 'partial'
                WHERE user_id = ? AND task_id = ? AND status != 'imported'
                """,
                (user_id_int, report["task_id"]),
            )

    return {
        "status": result_status,
        "result_id": report["result_id"],
        "task_id": report["task_id"],
        "deck_id": report["deck_id"],
        "imported_count": report["valid_count"],
        "requested_count": report["requested_count"],
        "missing_slide_ids": report["missing_slide_ids"],
        "duplicate": False,
        "duplicate_payload_matches": False,
        "source_path": provenance_path,
    }


def update_result_source_path(
    user_id: int,
    result_id: str,
    source_path: str | Path,
) -> bool:
    """Update provenance after an Inbox move, scoped to the owning user."""
    user_id_int = _user_id(user_id)
    if not isinstance(result_id, str) or not _SAFE_ID_RE.fullmatch(result_id):
        raise ValueError("result_id 无效。")
    clean_path = _source_path(None, source_path)
    db.init_db()
    with db.write_transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE chatgpt_explanation_results
            SET source_path = ?
            WHERE user_id = ? AND result_id = ?
            """,
            (clean_path, user_id_int, result_id),
        )
        return int(cursor.rowcount or 0) == 1


def _validate_payload(
    conn: sqlite3.Connection,
    user_id: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    report = _empty_report(payload)
    normalized_slides = _validate_result_schema(payload, report["errors"])
    report["schema_valid"] = not report["errors"]
    if not report["schema_valid"]:
        return _finalize_report(report)

    result_id = str(payload["result_id"])
    task_id = str(payload["task_id"])
    deck_id = int(payload["deck_id"])
    report.update({"result_id": result_id, "task_id": task_id, "deck_id": deck_id})
    existing_result = _existing_result(conn, user_id, result_id)
    report["duplicate"] = existing_result is not None
    report["already_imported"] = report["duplicate"]
    if report["duplicate"]:
        report["existing_source_path"] = str(existing_result["source_path"] or "")
        report["duplicate_payload_matches"] = _payload_matches_stored(
            existing_result, payload
        )
        if report["duplicate_payload_matches"]:
            report["warnings"].append("result_id 已导入，本次将跳过。")
        else:
            report["errors"].append(
                "result_id 已存在，但结果内容与首次导入记录不一致，拒绝复用。"
            )

    task_row = conn.execute(
        """
        SELECT *
        FROM chatgpt_explanation_tasks
        WHERE user_id = ? AND task_id = ?
        LIMIT 1
        """,
        (user_id, task_id),
    ).fetchone()
    if not task_row:
        report["errors"].append("task_id 不存在或不属于当前用户。")
        return _finalize_report(report)

    task = dict(task_row)
    report["task_exists"] = True
    report["task_status"] = str(task.get("status") or "")
    requested_slides = _requested_slides(task.get("requested_slides_json"), report["errors"])
    report["requested_count"] = len(requested_slides)
    if not requested_slides:
        report["errors"].append("任务没有有效的 requested slides。")

    task_deck_id = _strict_positive_int(task.get("deck_id"))
    if task_deck_id is None or deck_id != task_deck_id:
        report["errors"].append("deck_id 与任务记录不一致。")

    deck_row = None
    current_slide_rows: list[sqlite3.Row] = []
    if task_deck_id is not None:
        deck_row = conn.execute(
            """
            SELECT *
            FROM ppt_decks
            WHERE user_id = ? AND id = ?
            LIMIT 1
            """,
            (user_id, task_deck_id),
        ).fetchone()
        if deck_row:
            current_slide_rows = conn.execute(
                """
                SELECT *
                FROM ppt_slides
                WHERE user_id = ? AND deck_id = ?
                ORDER BY slide_number ASC, id ASC
                """,
                (user_id, task_deck_id),
            ).fetchall()
            report["deck_title"] = str(dict(deck_row).get("title") or "")
            report["deck_ok"] = True
        else:
            report["errors"].append("deck_id 对应的 PPT 不存在或不属于当前用户。")

    payload_fingerprint = str(payload["deck_fingerprint"])
    task_fingerprint = str(task.get("deck_fingerprint") or "")
    current_fingerprint = ""
    if deck_row:
        try:
            current_fingerprint = task_service.compute_deck_fingerprint(
                dict(deck_row), [dict(row) for row in current_slide_rows]
            )
        except Exception:
            report["errors"].append("无法计算当前 PPT 的 deck_fingerprint。")
    report["current_deck_fingerprint"] = current_fingerprint
    report["fingerprint_ok"] = bool(
        current_fingerprint
        and payload_fingerprint == task_fingerprint
        and task_fingerprint == current_fingerprint
    )
    if payload_fingerprint != task_fingerprint:
        report["errors"].append("deck_fingerprint 与任务记录不一致。")
    if current_fingerprint and task_fingerprint != current_fingerprint:
        report["errors"].append("deck_fingerprint 与当前 PPT 内容不一致，任务可能已经过期。")

    requested_by_id = {item["slide_id"]: item for item in requested_slides}
    current_by_id = {int(row["id"]): row for row in current_slide_rows}
    unknown_ids: list[int] = []
    valid_slides: list[dict[str, Any]] = []
    for slide in normalized_slides:
        slide_id = slide["slide_id"]
        expected = requested_by_id.get(slide_id)
        if expected is None:
            unknown_ids.append(slide_id)
            continue
        if slide["slide_number"] != expected["slide_number"]:
            report["errors"].append(
                f"slide_id {slide_id} 的 slide_number 与任务请求不一致。"
            )
            continue
        current = current_by_id.get(slide_id)
        if current is None:
            report["errors"].append(f"slide_id {slide_id} 不属于当前 PPT。")
            continue
        if int(current["slide_number"]) != slide["slide_number"]:
            report["errors"].append(
                f"slide_id {slide_id} 的 slide_number 与当前 PPT 不一致。"
            )
            continue
        valid_slides.append(slide)

    if unknown_ids:
        report["errors"].append(
            "结果包含任务请求范围外的 unknown slide_id："
            + ", ".join(str(slide_id) for slide_id in unknown_ids)
        )
    report["unknown_slide_ids"] = unknown_ids
    report["valid_slides"] = valid_slides
    report["valid_slide_ids"] = [slide["slide_id"] for slide in valid_slides]
    valid_ids = set(report["valid_slide_ids"])
    report["missing_slide_ids"] = [
        item["slide_id"] for item in requested_slides if item["slide_id"] not in valid_ids
    ]
    if report["missing_slide_ids"] and not report["errors"]:
        report["warnings"].append(
            f"部分结果：{len(valid_slides)} / {len(requested_slides)} 页。"
        )
    return _finalize_report(report)


def _validate_result_schema(
    payload: Mapping[str, Any], errors: list[str]
) -> list[dict[str, Any]]:
    payload_keys = set(payload)
    missing = [field for field in _TOP_LEVEL_FIELDS if field not in payload_keys]
    extra = sorted(payload_keys - _TOP_LEVEL_FIELDS)
    if missing:
        errors.append("结果 schema 缺少字段：" + ", ".join(sorted(missing)))
    if extra:
        errors.append("结果 schema 包含未支持字段：" + ", ".join(extra))

    if payload.get("package_type") != schema.RESULT_PACKAGE_TYPE:
        errors.append(f"package_type 必须是 {schema.RESULT_PACKAGE_TYPE}。")
    if payload.get("version") != schema.RESULT_SCHEMA_VERSION:
        errors.append(f"version 不受支持，仅支持 {schema.RESULT_SCHEMA_VERSION}。")
    if payload.get("generator") != schema.GENERATOR:
        errors.append(f"generator 必须是 {schema.GENERATOR}。")

    _validate_safe_id(payload.get("result_id"), "result_id", errors)
    _validate_safe_id(payload.get("task_id"), "task_id", errors)
    if _strict_positive_int(payload.get("deck_id")) is None:
        errors.append("deck_id 必须是正整数。")

    fingerprint = payload.get("deck_fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        errors.append("deck_fingerprint 必须是 sha256: 加 64 位小写十六进制。")

    generated_at = payload.get("generated_at")
    if not _valid_timestamp(generated_at):
        errors.append("generated_at 必须是有效的 ISO 8601 日期时间字符串。")

    raw_slides = payload.get("slides")
    if not isinstance(raw_slides, list) or not raw_slides:
        errors.append("slides 必须是非空数组。")
        return []
    if len(raw_slides) > schema.MAX_RESULT_SLIDES:
        errors.append(f"slides 过多，最多允许 {schema.MAX_RESULT_SLIDES} 页。")
        return []

    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_numbers: set[int] = set()
    for index, raw_slide in enumerate(raw_slides, start=1):
        label = f"slides[{index}]"
        if not isinstance(raw_slide, dict):
            errors.append(f"{label} 必须是 object。")
            continue
        keys = set(raw_slide)
        missing_slide_fields = sorted(_SLIDE_FIELDS - keys)
        extra_slide_fields = sorted(keys - _SLIDE_FIELDS)
        if missing_slide_fields:
            errors.append(f"{label} 缺少字段：" + ", ".join(missing_slide_fields))
        if extra_slide_fields:
            errors.append(f"{label} 包含未支持字段：" + ", ".join(extra_slide_fields))

        slide_id = _strict_positive_int(raw_slide.get("slide_id"))
        slide_number = _strict_positive_int(raw_slide.get("slide_number"))
        explanation = raw_slide.get("explanation")
        item_valid = not missing_slide_fields and not extra_slide_fields
        if slide_id is None:
            errors.append(f"{label}.slide_id 必须是正整数。")
            item_valid = False
        elif slide_id in seen_ids:
            errors.append(f"{label}.slide_id 重复：{slide_id}。")
            item_valid = False
        else:
            seen_ids.add(slide_id)
        if slide_number is None:
            errors.append(f"{label}.slide_number 必须是正整数。")
            item_valid = False
        elif slide_number in seen_numbers:
            errors.append(f"{label}.slide_number 重复：{slide_number}。")
            item_valid = False
        else:
            seen_numbers.add(slide_number)
        if not isinstance(explanation, str) or not explanation.strip():
            errors.append(f"{label}.explanation 必须是非空字符串。")
            item_valid = False
        elif not _valid_unicode_text(explanation):
            errors.append(f"{label}.explanation 包含无效 Unicode 字符。")
            item_valid = False
        elif len(explanation) > schema.MAX_EXPLANATION_CHARS:
            errors.append(
                f"{label}.explanation 过长，最多 {schema.MAX_EXPLANATION_CHARS} 个字符。"
            )
            item_valid = False
        if item_valid and slide_id is not None and slide_number is not None:
            normalized.append(
                {
                    "slide_id": slide_id,
                    "slide_number": slide_number,
                    "explanation": explanation,
                }
            )
    return normalized


def _requested_slides(raw_json: Any, errors: list[str]) -> list[dict[str, int]]:
    if not isinstance(raw_json, str):
        errors.append("任务 requested_slides_json 无效。")
        return []
    try:
        raw_items = schema.strict_json_loads(raw_json, require_object=False)
    except (TypeError, ValueError):
        errors.append("任务 requested_slides_json 无法解析。")
        return []
    if not isinstance(raw_items, list):
        errors.append("任务 requested_slides_json 必须是数组。")
        return []

    requested: list[dict[str, int]] = []
    seen_ids: set[int] = set()
    seen_numbers: set[int] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or set(raw_item) != {"slide_id", "slide_number"}:
            errors.append("任务 requested_slides_json 中存在无效页面。")
            return []
        slide_id = _strict_positive_int(raw_item.get("slide_id"))
        slide_number = _strict_positive_int(raw_item.get("slide_number"))
        if (
            slide_id is None
            or slide_number is None
            or slide_id in seen_ids
            or slide_number in seen_numbers
        ):
            errors.append("任务 requested_slides_json 中存在无效或重复页面。")
            return []
        seen_ids.add(slide_id)
        seen_numbers.add(slide_number)
        requested.append({"slide_id": slide_id, "slide_number": slide_number})
    return requested


def _empty_report(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "hard_valid": False,
        "schema_valid": False,
        "complete": False,
        "auto_import_allowed": False,
        "duplicate": False,
        "already_imported": False,
        "duplicate_payload_matches": None,
        "existing_source_path": "",
        "fingerprint_ok": False,
        "task_exists": False,
        "deck_ok": False,
        "errors": [],
        "warnings": [],
        "requested_count": 0,
        "valid_count": 0,
        "missing_count": 0,
        "unknown_count": 0,
        "missing_slide_ids": [],
        "unknown_slide_ids": [],
        "valid_slide_ids": [],
        "valid_slides": [],
        "result_id": "",
        "task_id": "",
        "deck_id": None,
        "deck_title": "",
        "task_status": "",
        "current_deck_fingerprint": "",
        "payload": dict(payload) if isinstance(payload, Mapping) else None,
        "status": "invalid",
    }


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    report["valid_count"] = len(report.get("valid_slides") or [])
    report["missing_count"] = len(report.get("missing_slide_ids") or [])
    report["unknown_count"] = len(report.get("unknown_slide_ids") or [])
    report["hard_valid"] = not report["errors"]
    report["complete"] = bool(
        report["hard_valid"]
        and report["requested_count"] > 0
        and report["valid_count"] == report["requested_count"]
        and not report["missing_slide_ids"]
    )
    report["auto_import_allowed"] = bool(
        report["complete"] and not report["duplicate"]
    )
    if report["errors"]:
        report["status"] = "invalid"
    elif report["duplicate"]:
        report["status"] = "already_imported"
    elif report["complete"]:
        report["status"] = "ready"
    else:
        report["status"] = "partial"
    return report


def _skipped_outcome(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "skipped",
        "result_id": report.get("result_id") or "",
        "task_id": report.get("task_id") or "",
        "deck_id": report.get("deck_id"),
        "imported_count": 0,
        "requested_count": int(report.get("requested_count") or 0),
        "missing_slide_ids": list(report.get("missing_slide_ids") or []),
        "duplicate": True,
        "duplicate_payload_matches": bool(report.get("duplicate_payload_matches")),
        "source_path": str(report.get("existing_source_path") or ""),
    }


def _read_result_bytes(source: Any) -> bytes:
    max_bytes = int(schema.MAX_RESULT_BYTES)
    if isinstance(source, bytes):
        raw = source
    elif isinstance(source, (bytearray, memoryview)):
        raw = bytes(source)
    elif isinstance(source, Path):
        raw = _read_path(source, max_bytes)
    elif isinstance(source, str):
        if source.lstrip().startswith(("{", "[")):
            raw = source.encode("utf-8")
        else:
            raw = _read_path(Path(source), max_bytes)
    elif isinstance(source, Mapping):
        raw = json.dumps(source, ensure_ascii=False).encode("utf-8")
    elif hasattr(source, "getbuffer"):
        raw = bytes(source.getbuffer())
    elif hasattr(source, "getvalue"):
        value = source.getvalue()
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    elif hasattr(source, "read"):
        value = source.read(max_bytes + 1)
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    else:
        raise ValueError("结果文件类型不受支持。")
    if len(raw) > max_bytes:
        raise ValueError(f"结果 JSON 过大，最大允许 {max_bytes} 字节。")
    return raw


def _read_path(path: Path, max_bytes: int) -> bytes:
    if not path.is_file():
        raise ValueError("结果文件不存在或不是普通文件。")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"结果 JSON 过大，最大允许 {max_bytes} 字节。")
    return path.read_bytes()


def _source_path(source: Any, explicit: str | Path | None) -> str:
    value: Any = explicit
    if value is None and isinstance(source, Path):
        value = source
    if value is None and isinstance(source, str) and not source.lstrip().startswith(("{", "[")):
        value = source
    if value is None:
        value = getattr(source, "name", "")
    clean = str(value or "").replace("\x00", "").strip()
    return clean[:2048]


def _existing_result(
    conn: sqlite3.Connection, user_id: int, result_id: str
) -> sqlite3.Row | None:
    if not result_id:
        return None
    row = conn.execute(
        """
        SELECT source_path, raw_result_json
        FROM chatgpt_explanation_results
        WHERE user_id = ? AND result_id = ?
        LIMIT 1
        """,
        (user_id, result_id),
    ).fetchone()
    return row


def _payload_matches_stored(
    existing_result: Mapping[str, Any], payload: Mapping[str, Any]
) -> bool:
    try:
        stored = schema.load_json_bytes(
            str(existing_result["raw_result_json"]).encode("utf-8")
        )
    except (KeyError, TypeError, ValueError):
        return False
    return stored == dict(payload)


def _user_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("user_id 必须是非负整数。")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("user_id 必须是非负整数。") from exc
    if normalized < 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValueError("user_id 必须是非负整数。")
    return normalized


def _strict_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return int(value)


def _validate_safe_id(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        errors.append(
            f"{field} 必须是 1-160 位且仅含字母、数字、点、下划线或连字符。"
        )


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 80:
        return False
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    if "T" not in candidate and " " not in candidate:
        return False
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def _valid_unicode_text(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _input_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    return "结果文件不是有效的 UTF-8 JSON。"
