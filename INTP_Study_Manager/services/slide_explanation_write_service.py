from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

import db
from services import chatgpt_explanation_schema as bridge_schema
from services import chatgpt_explanation_task_service as task_service


DEFAULT_MAX_ITEMS = bridge_schema.MAX_RESULT_SLIDES


class SlideExplanationWriteError(ValueError):
    """A stable domain error that adapters can map without exposing internals."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


def validate_explanation_text(value: Any) -> str:
    """Validate an explanation while preserving the caller's original text."""

    if not isinstance(value, str) or not value.strip():
        raise SlideExplanationWriteError("empty_explanation", "explanation 必须是非空字符串。")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SlideExplanationWriteError(
            "invalid_unicode", "explanation 包含无效 Unicode 字符。"
        ) from exc
    if len(value) > bridge_schema.MAX_EXPLANATION_CHARS:
        raise SlideExplanationWriteError(
            "explanation_too_long",
            f"explanation 过长，最多 {bridge_schema.MAX_EXPLANATION_CHARS} 个字符。",
        )
    return value


def append_slide_explanation(
    user_id: int,
    slide_id: int,
    slide_number: int,
    explanation: str,
    *,
    model: str,
    deck_id: int | None = None,
    expected_deck_fingerprint: str | None = None,
    source_context: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Append one immutable explanation version after ownership validation."""

    outcome = append_slide_explanations(
        user_id,
        [
            {
                "slide_id": slide_id,
                "slide_number": slide_number,
                "explanation": explanation,
                "source_context": source_context,
            }
        ],
        model=model,
        deck_id=deck_id,
        expected_deck_fingerprint=expected_deck_fingerprint,
        max_items=1,
        conn=conn,
    )
    return dict(outcome["items"][0])


def append_slide_explanations(
    user_id: int,
    slides: Sequence[Mapping[str, Any]],
    *,
    model: str,
    deck_id: int | None = None,
    expected_deck_fingerprint: str | None = None,
    max_items: int | None = DEFAULT_MAX_ITEMS,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Append a validated batch atomically, optionally inside a caller transaction."""

    normalized_user_id = _nonnegative_int(user_id, "user_id")
    normalized_model = _model_name(model)
    normalized_deck_id = _optional_positive_int(deck_id, "deck_id")
    normalized_slides = _normalize_slides(slides, max_items=max_items)
    expected = _optional_fingerprint(expected_deck_fingerprint)

    db.init_db()
    if conn is not None:
        return _append_in_transaction(
            conn,
            normalized_user_id,
            normalized_slides,
            model=normalized_model,
            deck_id=normalized_deck_id,
            expected_deck_fingerprint=expected,
        )
    with db.write_transaction() as transaction:
        return _append_in_transaction(
            transaction,
            normalized_user_id,
            normalized_slides,
            model=normalized_model,
            deck_id=normalized_deck_id,
            expected_deck_fingerprint=expected,
        )


def _append_in_transaction(
    conn: sqlite3.Connection,
    user_id: int,
    slides: list[dict[str, Any]],
    *,
    model: str,
    deck_id: int | None,
    expected_deck_fingerprint: str | None,
) -> dict[str, Any]:
    slide_ids = [int(item["slide_id"]) for item in slides]
    placeholders = ",".join("?" for _ in slide_ids)
    rows = conn.execute(
        f"""
        SELECT
            ps.id,
            ps.user_id,
            ps.deck_id,
            ps.slide_number
        FROM ppt_slides ps
        JOIN ppt_decks d
          ON d.id = ps.deck_id
         AND d.user_id = ps.user_id
        WHERE ps.user_id = ?
          AND d.user_id = ?
          AND ps.id IN ({placeholders})
        """,
        (user_id, user_id, *slide_ids),
    ).fetchall()
    owned_by_id = {int(row["id"]): row for row in rows}
    if len(owned_by_id) != len(slide_ids):
        raise SlideExplanationWriteError(
            "not_found", "一个或多个 slide 不存在或不属于当前用户。"
        )

    actual_deck_ids = {int(row["deck_id"]) for row in rows}
    if len(actual_deck_ids) != 1:
        raise SlideExplanationWriteError("mixed_decks", "批量页面必须属于同一个 deck。")
    actual_deck_id = next(iter(actual_deck_ids))
    if deck_id is not None and deck_id != actual_deck_id:
        raise SlideExplanationWriteError("deck_mismatch", "slide 与指定 deck_id 不一致。")

    seen_numbers: set[int] = set()
    for item in slides:
        expected_number = int(item["slide_number"])
        if expected_number in seen_numbers:
            raise SlideExplanationWriteError(
                "duplicate_slide_number", f"slide_number 重复：{expected_number}。"
            )
        seen_numbers.add(expected_number)
        stored_number = int(owned_by_id[int(item["slide_id"])]["slide_number"])
        if stored_number != expected_number:
            raise SlideExplanationWriteError(
                "slide_number_mismatch",
                f"slide_id {item['slide_id']} 的 slide_number 与当前 PPT 不一致。",
            )

    deck_row = conn.execute(
        "SELECT * FROM ppt_decks WHERE user_id = ? AND id = ? LIMIT 1",
        (user_id, actual_deck_id),
    ).fetchone()
    if not deck_row:
        raise SlideExplanationWriteError("not_found", "deck 不存在或不属于当前用户。")
    all_slide_rows = conn.execute(
        """
        SELECT *
        FROM ppt_slides
        WHERE user_id = ? AND deck_id = ?
        ORDER BY slide_number ASC, id ASC
        """,
        (user_id, actual_deck_id),
    ).fetchall()
    current_fingerprint = task_service.compute_deck_fingerprint(
        dict(deck_row), [dict(row) for row in all_slide_rows]
    )
    if expected_deck_fingerprint and expected_deck_fingerprint != current_fingerprint:
        raise SlideExplanationWriteError(
            "stale_deck_fingerprint", "deck_fingerprint 与当前 PPT 内容不一致。"
        )

    timestamp_row = conn.execute(
        "SELECT datetime('now', 'localtime') AS created_at"
    ).fetchone()
    now = str(timestamp_row["created_at"])
    inserted: list[dict[str, Any]] = []
    for item in slides:
        cursor = conn.execute(
            """
            INSERT INTO slide_explanations (
                user_id, slide_id, model, explanation, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, item["slide_id"], model, item["explanation"], now),
        )
        inserted.append(
            {
                "explanation_id": int(cursor.lastrowid),
                "slide_id": int(item["slide_id"]),
                "slide_number": int(item["slide_number"]),
                "deck_id": actual_deck_id,
                "model": model,
                "created_at": now,
            }
        )
    return {
        "deck_id": actual_deck_id,
        "deck_fingerprint": current_fingerprint,
        "count": len(inserted),
        "explanation_ids": [item["explanation_id"] for item in inserted],
        "items": inserted,
        "created_at": now,
    }


def _normalize_slides(
    slides: Sequence[Mapping[str, Any]], *, max_items: int | None
) -> list[dict[str, Any]]:
    if isinstance(slides, (str, bytes, bytearray)) or not isinstance(slides, Sequence):
        raise SlideExplanationWriteError("invalid_slides", "slides 必须是非空数组。")
    if not slides:
        raise SlideExplanationWriteError("invalid_slides", "slides 必须是非空数组。")
    if max_items is not None:
        normalized_max = _positive_int(max_items, "max_items")
        if len(slides) > normalized_max:
            raise SlideExplanationWriteError(
                "too_many_slides", f"一次最多保存 {normalized_max} 页。"
            )

    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for raw_item in slides:
        if not isinstance(raw_item, Mapping):
            raise SlideExplanationWriteError("invalid_slide", "slides 中每一项必须是 object。")
        slide_id = _positive_int(raw_item.get("slide_id"), "slide_id")
        if slide_id in seen_ids:
            raise SlideExplanationWriteError(
                "duplicate_slide_id", f"slide_id 重复：{slide_id}。"
            )
        seen_ids.add(slide_id)
        slide_number = _positive_int(raw_item.get("slide_number"), "slide_number")
        explanation = validate_explanation_text(raw_item.get("explanation"))
        source_context = raw_item.get("source_context")
        if source_context is not None:
            if not isinstance(source_context, str):
                raise SlideExplanationWriteError(
                    "invalid_source_context", "source_context 必须是字符串。"
                )
            try:
                source_context.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise SlideExplanationWriteError(
                    "invalid_source_context", "source_context 包含无效 Unicode 字符。"
                ) from exc
            if len(source_context) > 5_000:
                raise SlideExplanationWriteError(
                    "invalid_source_context", "source_context 最多 5000 个字符。"
                )
        normalized.append(
            {
                "slide_id": slide_id,
                "slide_number": slide_number,
                "explanation": explanation,
            }
        )
    return normalized


def _model_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SlideExplanationWriteError("invalid_model", "model 必须是非空字符串。")
    model = value.strip()
    if len(model) > 120:
        raise SlideExplanationWriteError("invalid_model", "model 过长。")
    try:
        model.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SlideExplanationWriteError("invalid_model", "model 包含无效 Unicode 字符。") from exc
    return model


def _optional_fingerprint(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 80:
        raise SlideExplanationWriteError(
            "invalid_deck_fingerprint", "expected_deck_fingerprint 无效。"
        )
    return value


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SlideExplanationWriteError("invalid_argument", f"{field} 必须是正整数。")
    return int(value)


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SlideExplanationWriteError("invalid_argument", f"{field} 必须是非负整数。")
    return int(value)
