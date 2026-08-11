from __future__ import annotations

import json
from typing import Any

from db import managed_connection, write_transaction

CONTEXT_VERSION = 1
ACTIVE_CONTEXT_SETTING_SUFFIX = "active_learning_context"
VALID_SELECTION_SOURCES = {"slide", "slide_text", "explanation", "question"}
SELECTION_SOURCE_ALIASES = {"question_answer": "question"}
MAX_SELECTION_TEXT_LENGTH = 1200
MAX_SELECTION_CONTEXT_LENGTH = 700

_CONTEXT_CONTENT_KEYS = (
    "user_id",
    "subject",
    "deck_id",
    "deck_title",
    "slide_id",
    "slide_number",
    "active_question_id",
    "selection",
    "context_version",
)


def active_context_setting_key(user_id: int) -> str:
    return f"user:{_coerce_user_id(user_id)}:{ACTIVE_CONTEXT_SETTING_SUFFIX}"


def set_active_deck(user_id: int, deck_id: int) -> dict[str, Any]:
    user_id = _coerce_user_id(user_id)
    deck_id = _coerce_positive_int(deck_id, "PPT")
    with write_transaction() as conn:
        deck = _owned_deck(conn, user_id, deck_id)
        if not deck:
            raise ValueError("PPT 不存在或不属于当前用户。")

        existing = _load_context(conn, user_id)
        valid_existing = _validated_context(conn, user_id, existing)
        if valid_existing and int(valid_existing["deck_id"]) == deck_id:
            candidate = dict(valid_existing)
            candidate["subject"] = str(deck.get("subject") or "")
            candidate["deck_title"] = str(deck.get("title") or "")
        else:
            candidate = _deck_context(user_id, deck)
        return _persist_context(conn, user_id, existing, candidate)


def set_active_slide(
    user_id: int,
    deck_id: int,
    slide_id: int | None = None,
    slide_number: int | None = None,
) -> dict[str, Any]:
    user_id = _coerce_user_id(user_id)
    deck_id = _coerce_positive_int(deck_id, "PPT")
    slide_id_value = _optional_positive_int(slide_id, "幻灯片")
    slide_number_value = _optional_positive_int(slide_number, "幻灯片页码")
    if slide_id_value is None and slide_number_value is None:
        raise ValueError("必须提供 slide_id 或 slide_number。")

    with write_transaction() as conn:
        slide = _owned_slide(
            conn,
            user_id,
            deck_id,
            slide_id=slide_id_value,
            slide_number=slide_number_value,
        )
        if not slide:
            raise ValueError("幻灯片不存在、不属于当前 PPT，或不属于当前用户。")

        existing = _load_context(conn, user_id)
        valid_existing = _validated_context(conn, user_id, existing)
        same_slide = bool(
            valid_existing
            and int(valid_existing["deck_id"]) == deck_id
            and int(valid_existing.get("slide_id") or 0) == int(slide["id"])
        )
        candidate = dict(valid_existing) if same_slide else _deck_context(user_id, slide)
        candidate.update(
            {
                "subject": str(slide.get("subject") or ""),
                "deck_id": deck_id,
                "deck_title": str(slide.get("deck_title") or ""),
                "slide_id": int(slide["id"]),
                "slide_number": int(slide["slide_number"]),
            }
        )
        if not same_slide:
            candidate["active_question_id"] = None
            candidate["selection"] = None
        return _persist_context(conn, user_id, existing, candidate)


def set_active_selection(
    user_id: int,
    source: str,
    selected_text: str | None = None,
    *,
    text: str | None = None,
    slide_id: int | None = None,
    question_id: int | None = None,
    context_before: str = "",
    context_after: str = "",
) -> dict[str, Any]:
    user_id = _coerce_user_id(user_id)
    source_value = SELECTION_SOURCE_ALIASES.get(str(source or "").strip(), str(source or "").strip())
    if source_value not in VALID_SELECTION_SOURCES:
        raise ValueError("选区来源必须是 slide、slide_text、explanation 或 question。")

    selection_text = str(selected_text if selected_text is not None else text or "").strip()
    before = str(context_before or "").strip()
    after = str(context_after or "").strip()
    if not selection_text:
        raise ValueError("选中文本不能为空。")
    if len(selection_text) > MAX_SELECTION_TEXT_LENGTH:
        raise ValueError(f"选中文本不能超过 {MAX_SELECTION_TEXT_LENGTH} 个字符。")
    if len(before) > MAX_SELECTION_CONTEXT_LENGTH or len(after) > MAX_SELECTION_CONTEXT_LENGTH:
        raise ValueError(f"选区前后文分别不能超过 {MAX_SELECTION_CONTEXT_LENGTH} 个字符。")

    slide_id_value = _optional_positive_int(slide_id, "幻灯片")
    question_id_value = _optional_positive_int(question_id, "插问")
    with write_transaction() as conn:
        existing = _load_context(conn, user_id)
        active = _validated_context(conn, user_id, existing)
        if not active or not active.get("slide_id"):
            raise ValueError("当前没有可用的活动幻灯片。")

        active_slide_id = int(active["slide_id"])
        if slide_id_value is not None and slide_id_value != active_slide_id:
            raise ValueError("选区必须属于当前页。")
        if question_id_value is not None:
            question = conn.execute(
                """
                SELECT id
                FROM slide_questions
                WHERE id = ? AND user_id = ? AND slide_id = ?
                """,
                (question_id_value, user_id, active_slide_id),
            ).fetchone()
            if not question:
                raise ValueError("插问不存在或不属于当前页。")

        candidate = dict(active)
        candidate["active_question_id"] = question_id_value if source_value == "question" else None
        candidate["selection"] = {
            "source": source_value,
            "text": selection_text,
            "slide_id": active_slide_id,
            "question_id": question_id_value,
            "context_before": before,
            "context_after": after,
        }
        return _persist_context(conn, user_id, existing, candidate)


def clear_active_selection(user_id: int) -> dict[str, Any]:
    user_id = _coerce_user_id(user_id)
    with write_transaction() as conn:
        existing = _load_context(conn, user_id)
        active = _validated_context(conn, user_id, existing)
        if not active:
            return {"active": False}
        candidate = dict(active)
        candidate["active_question_id"] = None
        candidate["selection"] = None
        return _persist_context(conn, user_id, existing, candidate)


def get_active_context(user_id: int) -> dict[str, Any]:
    user_id = _coerce_user_id(user_id)
    with managed_connection() as conn:
        context = _validated_context(conn, user_id, _load_context(conn, user_id))
    return _with_active(context) if context else {"active": False}


def _coerce_user_id(value: object) -> int:
    if isinstance(value, bool) or (
        isinstance(value, float) and not value.is_integer()
    ):
        raise ValueError("user_id 必须是非负整数。")
    try:
        user_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("user_id 必须是非负整数。") from exc
    if user_id < 0:
        raise ValueError("user_id 必须是非负整数。")
    return user_id


def _coerce_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or (
        isinstance(value, float) and not value.is_integer()
    ):
        raise ValueError(f"{label}编号必须是正整数。")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}编号必须是正整数。") from exc
    if parsed <= 0:
        raise ValueError(f"{label}编号必须是正整数。")
    return parsed


def _optional_positive_int(value: object, label: str) -> int | None:
    if value is None or value == "":
        return None
    return _coerce_positive_int(value, label)


def _owned_deck(conn, user_id: int, deck_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, user_id, title, subject
        FROM ppt_decks
        WHERE id = ? AND user_id = ?
        """,
        (deck_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def _owned_slide(
    conn,
    user_id: int,
    deck_id: int,
    *,
    slide_id: int | None = None,
    slide_number: int | None = None,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            s.id,
            s.deck_id,
            s.slide_number,
            d.title AS deck_title,
            d.subject AS subject
        FROM ppt_slides AS s
        JOIN ppt_decks AS d ON d.id = s.deck_id
        WHERE s.user_id = ?
          AND d.user_id = ?
          AND d.id = ?
          AND (? IS NULL OR s.id = ?)
          AND (? IS NULL OR s.slide_number = ?)
        """,
        (
            user_id,
            user_id,
            deck_id,
            slide_id,
            slide_id,
            slide_number,
            slide_number,
        ),
    ).fetchone()
    return dict(row) if row else None


def _deck_context(user_id: int, deck: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "subject": str(deck.get("subject") or ""),
        "deck_id": int(deck.get("deck_id") or deck["id"]),
        "deck_title": str(deck.get("deck_title") or deck.get("title") or ""),
        "slide_id": None,
        "slide_number": None,
        "active_question_id": None,
        "selection": None,
        "context_version": CONTEXT_VERSION,
    }


def _load_context(conn, user_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ? AND user_id = ?",
        (active_context_setting_key(user_id), user_id),
    ).fetchone()
    if not row:
        return None
    try:
        value = json.loads(row["value"] or "")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    try:
        stored_user_id = int(value.get("user_id"))
    except (TypeError, ValueError):
        return None
    return value if stored_user_id == user_id else None


def _validated_context(conn, user_id: int, context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not context:
        return None
    try:
        deck_id = int(context.get("deck_id") or 0)
    except (TypeError, ValueError):
        return None
    deck = _owned_deck(conn, user_id, deck_id)
    if not deck:
        return None

    result = _deck_context(user_id, deck)
    slide_id = _safe_positive_int(context.get("slide_id"))
    slide_number = _safe_positive_int(context.get("slide_number"))
    if slide_id is not None or slide_number is not None:
        slide = _owned_slide(
            conn,
            user_id,
            deck_id,
            slide_id=slide_id,
            slide_number=slide_number,
        )
        if not slide:
            return None
        result["slide_id"] = int(slide["id"])
        result["slide_number"] = int(slide["slide_number"])

    active_question_id = None
    selection = None
    if result["slide_id"] is None:
        pass
    else:
        selection = _validated_selection(
            conn,
            user_id,
            int(result["slide_id"]),
            context.get("selection"),
        )
        if selection and selection["source"] == "question":
            active_question_id = selection.get("question_id")
    result["active_question_id"] = active_question_id
    result["selection"] = selection
    result["updated_at"] = str(context.get("updated_at") or "")
    result["context_version"] = CONTEXT_VERSION
    return result


def _validated_selection(
    conn,
    user_id: int,
    slide_id: int,
    value: object,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    source = SELECTION_SOURCE_ALIASES.get(
        str(value.get("source") or "").strip(),
        str(value.get("source") or "").strip(),
    )
    text = value.get("text")
    before = value.get("context_before", "")
    after = value.get("context_after", "")
    stored_slide_id = _safe_positive_int(value.get("slide_id"))
    if (
        source not in VALID_SELECTION_SOURCES
        or not isinstance(text, str)
        or not text.strip()
        or len(text.strip()) > MAX_SELECTION_TEXT_LENGTH
        or not isinstance(before, str)
        or not isinstance(after, str)
        or len(before.strip()) > MAX_SELECTION_CONTEXT_LENGTH
        or len(after.strip()) > MAX_SELECTION_CONTEXT_LENGTH
        or stored_slide_id != slide_id
    ):
        return None

    question_id = _safe_positive_int(value.get("question_id"))
    if value.get("question_id") not in (None, "") and question_id is None:
        return None
    if question_id is not None:
        question = conn.execute(
            """
            SELECT id
            FROM slide_questions
            WHERE id = ? AND user_id = ? AND slide_id = ?
            """,
            (question_id, user_id, slide_id),
        ).fetchone()
        if not question:
            return None
    return {
        "source": source,
        "text": text.strip(),
        "slide_id": slide_id,
        "question_id": question_id,
        "context_before": before.strip(),
        "context_after": after.strip(),
    }


def _safe_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or (
        isinstance(value, float) and not value.is_integer()
    ):
        return None
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _context_content(context: dict[str, Any] | None) -> dict[str, Any] | None:
    if context is None:
        return None
    return {key: context.get(key) for key in _CONTEXT_CONTENT_KEYS}


def _persist_context(
    conn,
    user_id: int,
    existing: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    candidate = {key: candidate.get(key) for key in _CONTEXT_CONTENT_KEYS}
    candidate["user_id"] = user_id
    candidate["context_version"] = CONTEXT_VERSION
    if _context_content(existing) == _context_content(candidate):
        unchanged = dict(candidate)
        unchanged["updated_at"] = str((existing or {}).get("updated_at") or "")
        return _with_active(unchanged)

    timestamp_row = conn.execute("SELECT datetime('now', 'localtime') AS value").fetchone()
    candidate["updated_at"] = str(timestamp_row["value"] or "")
    payload = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
    cursor = conn.execute(
        """
        INSERT INTO app_settings (key, user_id, value, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        WHERE app_settings.user_id = excluded.user_id
        """,
        (active_context_setting_key(user_id), user_id, payload, candidate["updated_at"]),
    )
    if int(cursor.rowcount or 0) != 1:
        raise ValueError("Active Context 设置的用户范围发生冲突。")
    return _with_active(candidate)


def _with_active(context: dict[str, Any]) -> dict[str, Any]:
    return {"active": True, **context}
