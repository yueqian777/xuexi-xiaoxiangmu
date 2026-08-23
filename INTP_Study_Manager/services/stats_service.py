from __future__ import annotations

from db import fetch_all
from services.auth_service import require_login


def low_mastery_cards(
    limit: int = 10,
    *,
    user_id: int | None = None,
    include_archived: bool = True,
) -> list[dict]:
    user_id = user_id if user_id is not None else require_login().id
    archive_clause = "" if include_archived else "AND COALESCE(course.status, 'active') <> 'archived'"
    return fetch_all(
        f"""
        SELECT card.id, card.subject, card.topic, card.mastery, card.core_question
        FROM knowledge_cards AS card
        LEFT JOIN courses AS course
          ON course.id = card.course_id
         AND course.user_id = card.user_id
        WHERE card.user_id = ? AND card.mastery < 70
          {archive_clause}
        ORDER BY card.mastery ASC, card.created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    )


def recent_blockers(limit: int = 8, *, user_id: int | None = None) -> list[dict]:
    user_id = user_id if user_id is not None else require_login().id
    return fetch_all(
        """
        SELECT id, date, subject, title, blockers, mastery
        FROM study_sessions
        WHERE user_id = ? AND TRIM(blockers) != ''
        ORDER BY date DESC, id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )


def open_parking_questions(limit: int = 10, *, user_id: int | None = None) -> list[dict]:
    user_id = user_id if user_id is not None else require_login().id
    return fetch_all(
        """
        SELECT id, subject, question, source, status, created_at
        FROM parking_lot
        WHERE user_id = ? AND status != '已解决'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    )


def recent_knowledge_links(limit: int = 8, *, user_id: int | None = None) -> list[dict]:
    user_id = user_id if user_id is not None else require_login().id
    return fetch_all(
        """
        SELECT
            kl.relation_type,
            kl.relation_note,
            kl.compare_points,
            kl.created_at,
            source.subject AS source_subject,
            source.topic AS source_topic,
            target.subject AS target_subject,
            target.topic AS target_topic
        FROM knowledge_links kl
        JOIN knowledge_cards source ON source.id = kl.source_knowledge_id AND source.user_id = kl.user_id
        JOIN knowledge_cards target ON target.id = kl.target_knowledge_id AND target.user_id = kl.user_id
        WHERE kl.user_id = ?
        ORDER BY kl.created_at DESC, kl.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )


def mistake_cause_counts(subject: str | None = None, *, user_id: int | None = None) -> list[dict]:
    user_id = user_id if user_id is not None else require_login().id
    params: list = [user_id]
    where_clause = "WHERE user_id = ?"
    if subject:
        where_clause += " AND subject = ?"
        params.append(subject)
    return fetch_all(
        f"""
        SELECT cause_category, COUNT(*) AS count
        FROM mistakes
        {where_clause}
        GROUP BY cause_category
        ORDER BY count DESC, cause_category ASC
        """,
        tuple(params),
    )
