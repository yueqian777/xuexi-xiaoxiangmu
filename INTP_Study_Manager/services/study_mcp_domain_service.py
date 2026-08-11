from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import db
from repositories import ppt_repository
from services import chatgpt_explanation_task_service
from services import knowledge_card_service
from services import ppt_context_service
from services import question_to_knowledge_service
from services import review_service
from services.active_learning_context_service import get_active_context


MAX_SLIDE_RANGE = 25
MAX_NEIGHBOR_RADIUS = 2
MAX_QUESTION_CHARS = 20_000
MAX_QUESTION_ANSWER_CHARS = 100_000
MAX_QUESTION_QUOTE_CHARS = 20_000
MAX_KNOWLEDGE_QUERY_CHARS = 500
MAX_KNOWLEDGE_SUBJECT_CHARS = 200


class StudyDomainError(ValueError):
    """Expected, transport-neutral domain failure with a stable machine code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }
        if self.details:
            payload["error"]["details"] = dict(self.details)
        return payload


def get_current_slide(
    user_id: int,
    *,
    include_neighbor_context: bool = False,
    neighbor_radius: int = MAX_NEIGHBOR_RADIUS,
) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    radius = _bounded_non_negative_int(
        neighbor_radius,
        "neighbor_radius",
        maximum=MAX_NEIGHBOR_RADIUS,
        error_code="neighbor_radius_exceeded",
    )
    context = get_active_context(owner_id)
    if not context or not context.get("active"):
        raise StudyDomainError("active_context_missing", "No active learning context is available.")

    deck_id = _context_positive_int(context.get("deck_id"), "deck_id")
    slide_id = _context_positive_int(context.get("slide_id"), "slide_id")
    slide_number = _context_positive_int(context.get("slide_number"), "slide_number")
    slide = _get_owned_slide(owner_id, slide_id, expected_deck_id=deck_id)
    if not slide or int(slide["slide_number"]) != slide_number:
        raise StudyDomainError(
            "active_context_stale",
            "The active slide no longer matches the owned PPT context.",
        )

    sections = _owned_sections(owner_id, deck_id)
    fingerprint = chatgpt_explanation_task_service.deck_fingerprint(owner_id, deck_id)
    result: dict[str, Any] = {
        "deck": _deck_payload(slide),
        "deck_fingerprint": fingerprint,
        "section": _section_for_slide(sections, slide),
        **_slide_payload(slide),
        "latest_explanation": _latest_explanation(owner_id, slide_id),
        "neighbors": [],
    }
    if include_neighbor_context and radius:
        result["neighbors"] = _neighbor_slides(owner_id, deck_id, slide_number, radius, slide_id)
    return result


def read_slide_range(
    user_id: int,
    deck_id: int,
    start_slide: int,
    end_slide: int,
) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    owned_deck_id = _positive_int(deck_id, "deck_id")
    start = _positive_int(start_slide, "start_slide")
    end = _positive_int(end_slide, "end_slide")
    if start > end:
        raise StudyDomainError("invalid_slide_range", "start_slide must not exceed end_slide.")
    requested_count = end - start + 1
    if requested_count > MAX_SLIDE_RANGE:
        raise StudyDomainError(
            "slide_range_too_large",
            f"A slide range may contain at most {MAX_SLIDE_RANGE} pages.",
            details={"max_range": MAX_SLIDE_RANGE},
        )

    deck = _get_owned_deck(owner_id, owned_deck_id)
    if not deck:
        raise _resource_not_found("PPT")
    slide_rows = db.fetch_all(
        """
        SELECT
            ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
            ps.section_index, ps.page_type, ps.one_sentence_summary,
            ps.slide_role, ps.key_points,
            d.title AS deck_title, d.subject AS deck_subject,
            d.slide_count AS deck_slide_count
        FROM ppt_slides AS ps
        JOIN ppt_decks AS d
          ON d.id = ps.deck_id
         AND d.user_id = ps.user_id
        WHERE ps.user_id = ?
          AND d.user_id = ?
          AND ps.deck_id = ?
          AND ps.slide_number BETWEEN ? AND ?
        ORDER BY ps.slide_number ASC, ps.id ASC
        """,
        (owner_id, owner_id, owned_deck_id, start, end),
    )
    if len(slide_rows) != requested_count:
        raise _resource_not_found("slide range")

    latest = ppt_repository.latest_explanations_by_slide_ids(
        owner_id,
        [int(row["id"]) for row in slide_rows],
    )
    slides = []
    for row in slide_rows:
        slide_payload = _slide_payload(row)
        slide_payload["latest_explanation"] = _explanation_payload(latest.get(int(row["id"])))
        slides.append(slide_payload)

    sections = [
        section
        for section in _owned_sections(owner_id, owned_deck_id)
        if int(section["start_slide"]) <= end and int(section["end_slide"]) >= start
    ]
    fingerprint = chatgpt_explanation_task_service.deck_fingerprint(owner_id, owned_deck_id)
    return {
        "deck": _deck_payload(deck),
        "deck_fingerprint": fingerprint,
        "start_slide": start,
        "end_slide": end,
        "sections": sections,
        "slides": slides,
    }


def get_question_tree(user_id: int, slide_id: int) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    owned_slide_id = _positive_int(slide_id, "slide_id")
    slide = _get_owned_slide(owner_id, owned_slide_id)
    if not slide:
        raise _resource_not_found("slide")
    questions = ppt_repository.get_slide_question_tree(owned_slide_id, owner_id)
    return {
        "deck_id": int(slide["deck_id"]),
        "slide_id": owned_slide_id,
        "slide_number": int(slide["slide_number"]),
        "questions": [_question_payload(node) for node in questions],
    }


def get_knowledge_card(user_id: int, knowledge_id: int) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    card_id = _positive_int(knowledge_id, "knowledge_id")
    card = knowledge_card_service.get_knowledge_card(owner_id, card_id)
    if not card:
        raise _resource_not_found("knowledge card")
    return dict(card)


def search_knowledge(
    user_id: int,
    query: str,
    *,
    subject: str | None = None,
    limit: int = knowledge_card_service.DEFAULT_SEARCH_LIMIT,
) -> list[dict[str, Any]]:
    owner_id = _user_id(user_id)
    search_text = _required_text(query, "query", MAX_KNOWLEDGE_QUERY_CHARS)
    clean_subject = _optional_text(
        subject,
        "subject",
        MAX_KNOWLEDGE_SUBJECT_CHARS,
    )
    normalized_limit = _positive_int(limit, "limit")
    if normalized_limit > knowledge_card_service.MAX_SEARCH_LIMIT:
        raise StudyDomainError(
            "search_limit_exceeded",
            f"Knowledge search is limited to {knowledge_card_service.MAX_SEARCH_LIMIT} results.",
            details={"max_limit": knowledge_card_service.MAX_SEARCH_LIMIT},
        )
    return knowledge_card_service.search_knowledge_cards(
        owner_id,
        search_text,
        subject=clean_subject or None,
        limit=normalized_limit,
    )


def get_today_reviews(user_id: int) -> list[dict[str, Any]]:
    owner_id = _user_id(user_id)
    rows = review_service.get_today_review_tasks(user_id=owner_id)
    return [
        {
            "review_task_id": int(row["id"]),
            "knowledge_id": int(row["knowledge_id"]),
            "review_date": str(row.get("review_date") or ""),
            "review_stage": str(row.get("review_stage") or ""),
            "status": str(row.get("status") or ""),
            "result": str(row.get("result") or ""),
            "subject": str(row.get("subject") or ""),
            "topic": str(row.get("topic") or ""),
            "mastery": int(row.get("mastery") or 0),
        }
        for row in rows
    ]


def add_slide_question(
    user_id: int,
    slide_id: int,
    question: str,
    answer: str,
    *,
    parent_question_id: int | None = None,
    quote_text: str = "",
) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    owned_slide_id = _positive_int(slide_id, "slide_id")
    clean_question = _required_text(question, "question", MAX_QUESTION_CHARS)
    clean_answer = _required_text(answer, "answer", MAX_QUESTION_ANSWER_CHARS)
    clean_quote = _optional_text(quote_text, "quote_text", MAX_QUESTION_QUOTE_CHARS)
    parent_id = _optional_positive_int(parent_question_id, "parent_question_id")

    slide = _get_owned_slide(owner_id, owned_slide_id)
    if not slide:
        raise _resource_not_found("slide")
    try:
        question_id = ppt_repository.create_slide_question_tree_node(
            owner_id,
            owned_slide_id,
            clean_question,
            clean_answer,
            "ChatGPT MCP",
            quote_text=clean_quote,
            parent_question_id=parent_id,
            quote_source="question_answer" if parent_id is not None else "slide",
            quote_source_question_id=parent_id,
        )
    except ValueError as exc:
        raise StudyDomainError("invalid_parent_question", str(exc)) from exc

    row = db.fetch_one(
        """
        SELECT id, slide_id, root_question_id, parent_question_id, depth,
               sort_order, status, created_at
        FROM slide_questions
        WHERE id = ? AND user_id = ? AND slide_id = ?
        """,
        (question_id, owner_id, owned_slide_id),
    )
    if not row:
        raise StudyDomainError("write_failed", "The question could not be reloaded after creation.")
    return {
        "question_id": int(row["id"]),
        "slide_id": int(row["slide_id"]),
        "root_question_id": int(row["root_question_id"] or row["id"]),
        "parent_question_id": int(row["parent_question_id"]) if row["parent_question_id"] else None,
        "depth": int(row["depth"] or 0),
        "sort_order": int(row["sort_order"] or 0),
        "status": str(row["status"] or ""),
        "created_at": str(row["created_at"] or ""),
    }


def convert_question_to_knowledge(user_id: int, question_id: int) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    owned_question_id = _positive_int(question_id, "question_id")
    _require_owned_question(owner_id, owned_question_id)
    try:
        result = question_to_knowledge_service.convert_question_to_knowledge(
            owner_id,
            owned_question_id,
        )
    except ValueError as exc:
        raise StudyDomainError("resource_not_found", "Question is unavailable for conversion.") from exc
    return {
        "question_id": owned_question_id,
        "knowledge_id": int(result["knowledge_id"]),
        "created": bool(result["created"]),
    }


def mark_question_understood(user_id: int, question_id: int) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    owned_question_id = _positive_int(question_id, "question_id")
    _require_owned_question(owner_id, owned_question_id)
    changed = question_to_knowledge_service.mark_question_understood(owner_id, owned_question_id)
    if not changed:
        raise _resource_not_found("question")
    return {"question_id": owned_question_id, "understood": True, "status": "understood"}


def create_review_for_question(user_id: int, question_id: int) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    owned_question_id = _positive_int(question_id, "question_id")
    _require_owned_question(owner_id, owned_question_id)
    try:
        result = question_to_knowledge_service.ensure_question_review_tasks(
            owner_id,
            owned_question_id,
        )
    except ValueError as exc:
        raise StudyDomainError("resource_not_found", "Question is unavailable for review creation.") from exc
    return {
        "question_id": owned_question_id,
        "knowledge_id": int(result["knowledge_id"]),
        "created": bool(result["created"]),
        "review_tasks_ensured": True,
    }


def submit_review_result(user_id: int, task_id: int, result: str) -> dict[str, Any]:
    owner_id = _user_id(user_id)
    review_task_id = _positive_int(task_id, "task_id")
    try:
        submitted = review_service.submit_review_result(owner_id, review_task_id, result)
    except ValueError as exc:
        raise StudyDomainError("invalid_review_result", str(exc)) from exc
    if not submitted:
        raise StudyDomainError(
            "review_task_not_pending",
            "The review task does not exist, is not owned by the current user, or is already complete.",
        )
    return dict(submitted)


def _get_owned_deck(user_id: int, deck_id: int) -> dict[str, Any] | None:
    return db.fetch_one(
        """
        SELECT id AS deck_id, title, subject, slide_count
        FROM ppt_decks
        WHERE id = ? AND user_id = ?
        """,
        (int(deck_id), int(user_id)),
    )


def _get_owned_slide(
    user_id: int,
    slide_id: int,
    *,
    expected_deck_id: int | None = None,
) -> dict[str, Any] | None:
    deck_clause = ""
    params: list[Any] = [int(slide_id), int(user_id), int(user_id)]
    if expected_deck_id is not None:
        deck_clause = "AND ps.deck_id = ?"
        params.append(int(expected_deck_id))
    return db.fetch_one(
        f"""
        SELECT
            ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
            ps.section_index, ps.page_type, ps.one_sentence_summary,
            ps.slide_role, ps.key_points,
            d.title AS deck_title, d.subject AS deck_subject,
            d.slide_count AS deck_slide_count
        FROM ppt_slides AS ps
        JOIN ppt_decks AS d
          ON d.id = ps.deck_id
         AND d.user_id = ps.user_id
        WHERE ps.id = ?
          AND ps.user_id = ?
          AND d.user_id = ?
          {deck_clause}
        LIMIT 1
        """,
        tuple(params),
    )


def _require_owned_question(user_id: int, question_id: int) -> dict[str, Any]:
    row = db.fetch_one(
        """
        SELECT sq.id, sq.slide_id, ps.deck_id
        FROM slide_questions AS sq
        JOIN ppt_slides AS ps
          ON ps.id = sq.slide_id
         AND ps.user_id = sq.user_id
        JOIN ppt_decks AS d
          ON d.id = ps.deck_id
         AND d.user_id = ps.user_id
        WHERE sq.id = ?
          AND sq.user_id = ?
          AND ps.user_id = ?
          AND d.user_id = ?
        LIMIT 1
        """,
        (int(question_id), int(user_id), int(user_id), int(user_id)),
    )
    if not row:
        raise _resource_not_found("question")
    return row


def _owned_sections(user_id: int, deck_id: int) -> list[dict[str, Any]]:
    return [
        _section_payload(section)
        for section in ppt_context_service.fetch_deck_sections(deck_id, user_id=user_id)
    ]


def _neighbor_slides(
    user_id: int,
    deck_id: int,
    slide_number: int,
    radius: int,
    current_slide_id: int,
) -> list[dict[str, Any]]:
    rows = db.fetch_all(
        """
        SELECT
            ps.id, ps.deck_id, ps.slide_number, ps.title, ps.slide_text,
            ps.section_index, ps.page_type, ps.one_sentence_summary,
            ps.slide_role, ps.key_points
        FROM ppt_slides AS ps
        JOIN ppt_decks AS d
          ON d.id = ps.deck_id
         AND d.user_id = ps.user_id
        WHERE ps.user_id = ?
          AND d.user_id = ?
          AND ps.deck_id = ?
          AND ps.slide_number BETWEEN ? AND ?
          AND ps.id != ?
        ORDER BY ps.slide_number ASC, ps.id ASC
        """,
        (
            int(user_id),
            int(user_id),
            int(deck_id),
            max(1, int(slide_number) - int(radius)),
            int(slide_number) + int(radius),
            int(current_slide_id),
        ),
    )
    return [_slide_payload(row) for row in rows]


def _deck_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "deck_id": int(row.get("deck_id") or row.get("id") or 0),
        "title": str(row.get("deck_title") or row.get("title") or ""),
        "subject": str(row.get("deck_subject") or row.get("subject") or ""),
        "slide_count": int(row.get("deck_slide_count") or row.get("slide_count") or 0),
    }


def _slide_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "slide_id": int(row.get("id") or row.get("slide_id") or 0),
        "slide_number": int(row.get("slide_number") or 0),
        "title": str(row.get("title") or ""),
        "slide_text": str(row.get("slide_text") or ""),
        "section_index": int(row.get("section_index") or 0),
        "page_type": str(row.get("page_type") or ""),
        "slide_role": str(row.get("slide_role") or ""),
        "key_points": str(row.get("key_points") or ""),
        "one_sentence_summary": str(row.get("one_sentence_summary") or ""),
    }


def _section_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "section_index": int(row.get("section_index") or 0),
        "title": str(row.get("title") or ""),
        "topic": str(row.get("topic") or ""),
        "core_question": str(row.get("core_question") or ""),
        "summary": str(row.get("summary") or ""),
        "key_terms": [str(item) for item in row.get("key_terms") or []],
        "prerequisite_concepts": [
            str(item) for item in row.get("prerequisite_concepts") or []
        ],
        "start_slide": int(row.get("start_slide") or 0),
        "end_slide": int(row.get("end_slide") or 0),
    }


def _section_for_slide(
    sections: list[dict[str, Any]],
    slide: Mapping[str, Any],
) -> dict[str, Any] | None:
    section_index = int(slide.get("section_index") or 0)
    slide_number = int(slide.get("slide_number") or 0)
    exact = next(
        (section for section in sections if int(section["section_index"]) == section_index),
        None,
    )
    if exact:
        return exact
    return next(
        (
            section
            for section in sections
            if int(section["start_slide"]) <= slide_number <= int(section["end_slide"])
        ),
        None,
    )


def _latest_explanation(user_id: int, slide_id: int) -> dict[str, Any] | None:
    return _explanation_payload(ppt_repository.latest_explanation(user_id, slide_id))


def _explanation_payload(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "explanation_id": int(row.get("id") or 0),
        "model": str(row.get("model") or ""),
        "explanation": str(row.get("explanation") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


def _question_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    children = row.get("children") if isinstance(row.get("children"), list) else []
    return {
        "id": int(row.get("id") or 0),
        "slide_id": int(row.get("slide_id") or 0),
        "question": str(row.get("question") or ""),
        "quote_text": str(row.get("quote_text") or ""),
        "answer": str(row.get("answer") or ""),
        "model": str(row.get("model") or ""),
        "category": str(row.get("category") or ""),
        "status": str(row.get("status") or ""),
        "knowledge_id": int(row["knowledge_id"]) if row.get("knowledge_id") else None,
        "converted_to_knowledge": bool(row.get("converted_to_knowledge")),
        "understood": bool(row.get("understood")),
        "need_review": bool(row.get("need_review")),
        "sort_order": int(row.get("sort_order") or 0),
        "root_question_id": int(row.get("root_question_id") or row.get("id") or 0),
        "parent_question_id": (
            int(row["parent_question_id"]) if row.get("parent_question_id") else None
        ),
        "depth": int(row.get("depth") or 0),
        "quote_source": str(row.get("quote_source") or "slide"),
        "quote_source_question_id": (
            int(row["quote_source_question_id"])
            if row.get("quote_source_question_id")
            else None
        ),
        "created_at": str(row.get("created_at") or ""),
        "children": [_question_payload(child) for child in children],
    }


def _user_id(value: Any) -> int:
    parsed = _non_negative_int(value, "user_id")
    return parsed


def _positive_int(value: Any, label: str) -> int:
    parsed = _non_negative_int(value, label)
    if parsed <= 0:
        raise StudyDomainError("invalid_argument", f"{label} must be a positive integer.")
    return parsed


def _optional_positive_int(value: Any, label: str) -> int | None:
    if value is None or value == "":
        return None
    return _positive_int(value, label)


def _context_positive_int(value: Any, label: str) -> int:
    try:
        return _positive_int(value, label)
    except StudyDomainError as exc:
        raise StudyDomainError(
            "active_context_stale",
            f"The active context has no valid {label}.",
        ) from exc


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise StudyDomainError("invalid_argument", f"{label} must be a non-negative integer.")
    if isinstance(value, float) and not value.is_integer():
        raise StudyDomainError("invalid_argument", f"{label} must be a non-negative integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise StudyDomainError(
            "invalid_argument",
            f"{label} must be a non-negative integer.",
        ) from exc
    if parsed < 0:
        raise StudyDomainError("invalid_argument", f"{label} must be a non-negative integer.")
    return parsed


def _bounded_non_negative_int(
    value: Any,
    label: str,
    *,
    maximum: int,
    error_code: str,
) -> int:
    parsed = _non_negative_int(value, label)
    if parsed > maximum:
        raise StudyDomainError(
            error_code,
            f"{label} must not exceed {maximum}.",
            details={"maximum": maximum},
        )
    return parsed


def _required_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise StudyDomainError("invalid_argument", f"{label} must be text.")
    text = value.strip()
    if not text:
        raise StudyDomainError("invalid_argument", f"{label} must not be empty.")
    if len(text) > maximum:
        raise StudyDomainError(
            "input_too_long",
            f"{label} must not exceed {maximum} characters.",
            details={"field": label, "maximum": maximum},
        )
    if not _valid_unicode(text):
        raise StudyDomainError("invalid_unicode", f"{label} contains invalid Unicode text.")
    return text


def _optional_text(value: Any, label: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise StudyDomainError("invalid_argument", f"{label} must be text.")
    text = value.strip()
    if len(text) > maximum:
        raise StudyDomainError(
            "input_too_long",
            f"{label} must not exceed {maximum} characters.",
            details={"field": label, "maximum": maximum},
        )
    if text and not _valid_unicode(text):
        raise StudyDomainError("invalid_unicode", f"{label} contains invalid Unicode text.")
    return text


def _valid_unicode(value: str) -> bool:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return not any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _resource_not_found(target: str) -> StudyDomainError:
    return StudyDomainError(
        "resource_not_found",
        f"The requested {target} does not exist or is not owned by the current user.",
    )
