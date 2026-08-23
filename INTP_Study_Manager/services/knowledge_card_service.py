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
    "course_id",
    "source_session_id",
    "source_deck_id",
    "source_slide_id",
    "source_question_id",
    "created_at",
)


def list_knowledge_cards_with_context(
    user_id: int,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """List user-owned cards with their learning source and next review.

    Direct question/slide provenance wins. Cards created from a generated study
    session use its recorded deck and page range without claiming a false exact
    page. Archived course cards stay searchable through an explicit opt-in, but
    do not crowd the default current-learning view.
    """

    owner_id = _non_negative_int(user_id, "user_id")
    archive_clause = "" if include_archived else "AND COALESCE(c.status, 'active') <> 'archived'"
    return fetch_all(
        f"""
        SELECT
            kc.*,
            c.name AS course_name,
            c.status AS course_status,
            COALESCE(
                direct_deck.title,
                (
                    SELECT session_deck.title
                    FROM ppt_study_asset_pages asset_page
                    JOIN ppt_decks session_deck
                      ON session_deck.id = asset_page.deck_id
                     AND session_deck.user_id = asset_page.user_id
                    WHERE asset_page.user_id = kc.user_id
                      AND asset_page.session_id = kc.source_session_id
                    ORDER BY asset_page.id ASC
                    LIMIT 1
                )
            ) AS source_deck_title,
            direct_slide.slide_number AS source_slide_number,
            CASE
                WHEN direct_slide.id IS NOT NULL THEN ''
                ELSE COALESCE(
                    (
                        SELECT NULLIF(TRIM(asset_page.range_label), '')
                        FROM ppt_study_asset_pages asset_page
                        WHERE asset_page.user_id = kc.user_id
                          AND asset_page.session_id = kc.source_session_id
                          AND TRIM(COALESCE(asset_page.range_label, '')) != ''
                        ORDER BY asset_page.id ASC
                        LIMIT 1
                    ),
                    (
                        SELECT CASE
                            WHEN MIN(asset_page.slide_number) = MAX(asset_page.slide_number)
                                THEN '第 ' || MIN(asset_page.slide_number) || ' 页'
                            ELSE '第 ' || MIN(asset_page.slide_number) || '-' || MAX(asset_page.slide_number) || ' 页'
                        END
                        FROM ppt_study_asset_pages asset_page
                        WHERE asset_page.user_id = kc.user_id
                          AND asset_page.session_id = kc.source_session_id
                    ),
                    ''
                )
            END AS source_page_range,
            source_question.question AS source_question,
            (
                SELECT MIN(review_task.review_date)
                FROM review_tasks review_task
                WHERE review_task.user_id = kc.user_id
                  AND review_task.knowledge_id = kc.id
                  AND review_task.status = '待复习'
            ) AS next_review_date
        FROM knowledge_cards kc
        LEFT JOIN courses c
          ON c.id = kc.course_id
         AND c.user_id = kc.user_id
        LEFT JOIN ppt_decks direct_deck
          ON direct_deck.id = kc.source_deck_id
         AND direct_deck.user_id = kc.user_id
        LEFT JOIN ppt_slides direct_slide
          ON direct_slide.id = kc.source_slide_id
         AND direct_slide.user_id = kc.user_id
        LEFT JOIN slide_questions source_question
          ON source_question.id = kc.source_question_id
         AND source_question.user_id = kc.user_id
        WHERE kc.user_id = ?
          {archive_clause}
        ORDER BY kc.created_at DESC, kc.id DESC
        """,
        (owner_id,),
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
    course_name = _text(card.get("course_name")) or subject
    source_deck = _text(card.get("source_deck_title"))
    source_slide = _safe_int(card.get("source_slide_number"), 0)
    source_page_range = _text(card.get("source_page_range"))
    source_question = _text(card.get("source_question"))
    next_review_date = _text(card.get("next_review_date")) or "暂无待复习任务"
    stars = _mastery_stars(level["score"])

    source_parts = [course_name]
    if source_deck:
        source_parts.append(source_deck)
    if source_slide > 0:
        source_parts.append(f"第 {source_slide} 页")
    elif source_page_range:
        source_parts.append(f"页码范围：{source_page_range}")
    source_lines = [f"**来源**\n\n{' · '.join(source_parts)}"]
    if source_question:
        source_lines.append(f"**来源插问**\n\n{source_question}")

    return "\n\n".join(
        [
            f"### {topic}",
            f"`{subject}` · 掌握度 **{level['score']}%** · **{level['label']}**",
            *source_lines,
            f"**掌握**\n\n{stars}（{level['score']}%）",
            f"**下次复习**\n\n{next_review_date}",
            f"**核心问题**\n\n{core_question}",
            f"**一句话抓手**\n\n{one_sentence}",
            f"**公式 / 推导**\n\n{logic_or_formula}",
            f"**应用 / 快速定位**\n\n{application}",
            f"**下一步**\n\n{level['hint']}",
        ]
    )


def _mastery_stars(value: Any) -> str:
    score = clamp_mastery(_safe_int(value, 0))
    filled = max(0, min(5, (score + 10) // 20))
    return "★" * filled + "☆" * (5 - filled)


def compact_card_index_rows(cards: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        level = mastery_level(card.get("mastery", 0))
        rows.append(
            {
                "id": int(card.get("id") or 0),
                "科目": _text(card.get("subject")),
                "课程状态": _course_status_label(card.get("course_status")),
                "知识点": _text(card.get("topic")),
                "核心问题": _clip(_text(card.get("core_question")), 72),
                "掌握度": int(level["score"]),
                "状态": str(level["label"]),
                "需要复习": "是" if bool(card.get("need_review")) else "否",
                "下次复习": _text(card.get("next_review_date")) or "—",
                "创建时间": _text(card.get("created_at")),
            }
        )
    return rows


def _course_status_label(value: Any) -> str:
    return {
        "active": "学习中",
        "completed": "已完成",
        "archived": "已归档",
    }.get(_text(value), "未绑定")


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
