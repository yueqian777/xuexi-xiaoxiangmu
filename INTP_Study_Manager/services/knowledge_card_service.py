from __future__ import annotations

from typing import Any, Mapping

from db import fetch_all, fetch_one
from services.mastery_service import clamp_mastery


DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 50

KNOWLEDGE_CARD_FIELDS = (
    "id",
    "subject",
    "topic",
    "core_question",
    "one_sentence",
    "logic_or_formula",
    "application",
    "mastery",
    "need_review",
    "source_session_id",
    "source_deck_id",
    "source_slide_id",
    "source_question_id",
    "created_at",
)


def get_knowledge_card(user_id: int, knowledge_id: int) -> dict[str, Any] | None:
    """Return one explicitly user-scoped card without leaking the owner column."""

    owner_id = _non_negative_int(user_id, "user_id")
    card_id = _positive_int(knowledge_id, "knowledge_id")
    fields = ", ".join(KNOWLEDGE_CARD_FIELDS)
    return fetch_one(
        f"SELECT {fields} FROM knowledge_cards WHERE user_id = ? AND id = ?",
        (owner_id, card_id),
    )


def search_knowledge_cards(
    user_id: int,
    query: str,
    *,
    subject: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[dict[str, Any]]:
    """Search a bounded, user-owned knowledge-card corpus using literal LIKE text."""

    owner_id = _non_negative_int(user_id, "user_id")
    search_text = str(query or "").strip()
    if not search_text:
        raise ValueError("query must not be empty")
    result_limit = _positive_int(limit, "limit")
    if result_limit > MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must not exceed {MAX_SEARCH_LIMIT}")

    escaped = _escape_like(search_text)
    pattern = f"%{escaped}%"
    clauses = [
        """
        (
            subject LIKE ? ESCAPE '\\'
            OR topic LIKE ? ESCAPE '\\'
            OR COALESCE(core_question, '') LIKE ? ESCAPE '\\'
            OR COALESCE(one_sentence, '') LIKE ? ESCAPE '\\'
            OR COALESCE(logic_or_formula, '') LIKE ? ESCAPE '\\'
            OR COALESCE(application, '') LIKE ? ESCAPE '\\'
        )
        """
    ]
    params: list[Any] = [owner_id, *([pattern] * 6)]
    clean_subject = str(subject or "").strip()
    if clean_subject:
        clauses.append("subject = ?")
        params.append(clean_subject)
    params.append(result_limit)

    fields = ", ".join(KNOWLEDGE_CARD_FIELDS)
    return fetch_all(
        f"""
        SELECT {fields}
        FROM knowledge_cards
        WHERE user_id = ?
          AND {' AND '.join(clauses)}
        ORDER BY mastery ASC, created_at DESC, id DESC
        LIMIT ?
        """,
        tuple(params),
    )


def mastery_level(value: Any) -> dict[str, str | int]:
    score = clamp_mastery(_safe_int(value, 0))
    if score >= 85:
        return {
            "score": score,
            "label": "迁移熟练",
            "hint": "优先做变式题和跨章节迁移。",
        }
    if score >= 70:
        return {
            "score": score,
            "label": "基本掌握",
            "hint": "用闭卷解释和典型题保持稳定。",
        }
    if score >= 45:
        return {
            "score": score,
            "label": "巩固中",
            "hint": "先补公式条件、推导断点和易混点。",
        }
    return {
        "score": score,
        "label": "薄弱",
        "hint": "今天优先复习，先重新回答核心问题。",
    }


def knowledge_card_preview_markdown(card: Mapping[str, Any]) -> str:
    level = mastery_level(card.get("mastery", 0))
    subject = _text(card.get("subject")) or "未分类"
    topic = _text(card.get("topic")) or "未命名知识点"
    core_question = _text(card.get("core_question")) or "待补充核心问题"
    one_sentence = _text(card.get("one_sentence")) or "待补充一句话解释"
    logic_or_formula = _text(card.get("logic_or_formula")) or "待补充公式、推导或因果链"
    application = _text(card.get("application")) or "待补充典型题、应用场景或识别信号"

    return "\n\n".join(
        [
            f"### {topic}",
            f"`{subject}` · 掌握度 **{level['score']}%** · **{level['label']}**",
            f"**核心问题**\n\n{core_question}",
            f"**一句话抓手**\n\n{one_sentence}",
            f"**公式 / 推导**\n\n{logic_or_formula}",
            f"**应用 / 快速定位**\n\n{application}",
            f"**下一步**\n\n{level['hint']}",
        ]
    )


def compact_card_index_rows(cards: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        level = mastery_level(card.get("mastery", 0))
        rows.append(
            {
                "id": int(card.get("id") or 0),
                "科目": _text(card.get("subject")),
                "知识点": _text(card.get("topic")),
                "核心问题": _clip(_text(card.get("core_question")), 72),
                "掌握度": int(level["score"]),
                "状态": str(level["label"]),
                "需要复习": "是" if bool(card.get("need_review")) else "否",
                "创建时间": _text(card.get("created_at")),
            }
        )
    return rows


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{label} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return parsed


def _positive_int(value: Any, label: str) -> int:
    parsed = _non_negative_int(value, label)
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
