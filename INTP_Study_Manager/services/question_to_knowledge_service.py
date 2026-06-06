from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from db import fetch_one, write_transaction
from services.review_service import ensure_initial_review_tasks


DEFAULT_SUBJECT = "Uncategorized"


def get_question_knowledge_draft(user_id: int, question_id: int) -> dict[str, Any] | None:
    row = _fetch_question_context(int(user_id), int(question_id))
    if not row:
        return None
    return _draft_from_context(row)


def convert_question_to_knowledge(
    user_id: int,
    question_id: int,
    overrides: Mapping[str, Any] | None = None,
    create_review_tasks: bool = True,
) -> dict[str, Any]:
    user_id_int = int(user_id)
    question_id_int = int(question_id)
    override_values = dict(overrides or {})
    created = False

    with write_transaction() as conn:
        row = conn.execute(
            """
            SELECT
                sq.*,
                ps.id AS source_slide_id,
                ps.deck_id AS source_deck_id,
                ps.slide_number,
                ps.title AS slide_title,
                ps.slide_text,
                d.subject AS deck_subject,
                d.title AS deck_title
            FROM slide_questions sq
            LEFT JOIN ppt_slides ps ON ps.id = sq.slide_id AND ps.user_id = sq.user_id
            LEFT JOIN ppt_decks d ON d.id = ps.deck_id AND d.user_id = sq.user_id
            WHERE sq.user_id = ? AND sq.id = ?
            """,
            (user_id_int, question_id_int),
        ).fetchone()
        if not row:
            raise ValueError("slide question not found")

        question_row = dict(row)
        current_card = _fetch_valid_card_for_question(conn, user_id_int, question_row)
        if current_card:
            knowledge_id = int(current_card["id"])
        else:
            conn.execute(
                """
                UPDATE slide_questions
                SET knowledge_id = NULL, converted_to_knowledge = 0
                WHERE user_id = ? AND id = ?
                """,
                (user_id_int, question_id_int),
            )
            draft = _draft_from_context(question_row)
            draft.update(_clean_overrides(override_values))
            cursor = conn.execute(
                """
                INSERT INTO knowledge_cards (
                    user_id, subject, topic, core_question, one_sentence, logic_or_formula,
                    application, mastery, need_review, source_deck_id, source_slide_id, source_question_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id_int,
                    draft["subject"],
                    draft["topic"],
                    draft["core_question"],
                    draft["one_sentence"],
                    draft["logic_or_formula"],
                    draft["application"],
                    int(draft["mastery"]),
                    int(bool(draft["need_review"])),
                    draft.get("source_deck_id"),
                    draft.get("source_slide_id"),
                    question_id_int,
                ),
            )
            knowledge_id = int(cursor.lastrowid)
            created = True

        need_review = bool(override_values.get("need_review", create_review_tasks))
        conn.execute(
            """
            UPDATE slide_questions
            SET knowledge_id = ?, converted_to_knowledge = 1, need_review = ?
            WHERE user_id = ? AND id = ?
            """,
            (knowledge_id, int(need_review), user_id_int, question_id_int),
        )

    if create_review_tasks or need_review:
        ensure_initial_review_tasks(knowledge_id, date.today(), user_id=user_id_int)
    return {"knowledge_id": knowledge_id, "created": created}


def ensure_question_review_tasks(user_id: int, question_id: int) -> dict[str, Any]:
    return convert_question_to_knowledge(
        user_id,
        question_id,
        overrides={"need_review": True},
        create_review_tasks=True,
    )


def mark_question_understood(user_id: int, question_id: int) -> bool:
    with write_transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE slide_questions
            SET understood = 1, status = ?
            WHERE user_id = ? AND id = ?
            """,
            ("understood", int(user_id), int(question_id)),
        )
        return int(cursor.rowcount or 0) > 0


def _fetch_question_context(user_id: int, question_id: int) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT
            sq.*,
            ps.id AS source_slide_id,
            ps.deck_id AS source_deck_id,
            ps.slide_number,
            ps.title AS slide_title,
            ps.slide_text,
            d.subject AS deck_subject,
            d.title AS deck_title
        FROM slide_questions sq
        LEFT JOIN ppt_slides ps ON ps.id = sq.slide_id AND ps.user_id = sq.user_id
        LEFT JOIN ppt_decks d ON d.id = ps.deck_id AND d.user_id = sq.user_id
        WHERE sq.user_id = ? AND sq.id = ?
        """,
        (int(user_id), int(question_id)),
    )
    return dict(row) if row else None


def _fetch_valid_card_for_question(conn, user_id: int, question: Mapping[str, Any]):
    knowledge_id = question.get("knowledge_id")
    if knowledge_id:
        card = conn.execute(
            """
            SELECT id
            FROM knowledge_cards
            WHERE user_id = ? AND id = ?
            """,
            (int(user_id), int(knowledge_id)),
        ).fetchone()
        if card:
            return card
    return conn.execute(
        """
        SELECT id
        FROM knowledge_cards
        WHERE user_id = ? AND source_question_id = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(user_id), int(question["id"])),
    ).fetchone()


def _draft_from_context(row: Mapping[str, Any]) -> dict[str, Any]:
    question = _text(row.get("question"))
    answer = _text(row.get("answer"))
    subject = _text(row.get("deck_subject")) or DEFAULT_SUBJECT
    topic = _short_title(question) or f"Question {row.get('id')}"
    slide_number = row.get("slide_number")
    slide_title = _text(row.get("slide_title"))
    deck_title = _text(row.get("deck_title"))
    slide_text = _text(row.get("slide_text"))
    first_paragraph = _first_paragraph(answer)
    source_lines = []
    if deck_title:
        source_lines.append(f"Deck: {deck_title}")
    if slide_number:
        source_lines.append(f"Slide {slide_number}: {slide_title or 'Untitled'}")
    if slide_text:
        source_lines.append(f"Slide summary: {_clip(slide_text, 240)}")
    return {
        "subject": subject,
        "topic": topic,
        "core_question": question,
        "one_sentence": _clip(first_paragraph, 220) or "Pending summary",
        "logic_or_formula": "\n\n".join(part for part in ["Source question answer:", answer] if part),
        "application": "\n".join(source_lines) or "Source slide is unavailable.",
        "mastery": 60,
        "need_review": True,
        "source_deck_id": row.get("source_deck_id"),
        "source_slide_id": row.get("source_slide_id"),
        "source_question_id": row.get("id"),
    }


def _clean_overrides(overrides: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key in ["subject", "topic", "core_question", "one_sentence", "logic_or_formula", "application"]:
        value = _text(overrides.get(key))
        if value:
            cleaned[key] = value
    if "mastery" in overrides:
        cleaned["mastery"] = max(0, min(100, _safe_int(overrides.get("mastery"), 60)))
    if "need_review" in overrides:
        cleaned["need_review"] = bool(overrides.get("need_review"))
    return cleaned


def _first_paragraph(value: str) -> str:
    for part in value.split("\n\n"):
        if part.strip():
            return " ".join(part.split())
    return " ".join(value.split())


def _short_title(value: str, limit: int = 48) -> str:
    text = " ".join(value.split())
    text = text.strip(" ?.!:;")
    return _clip(text, limit)


def _clip(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "..."


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
