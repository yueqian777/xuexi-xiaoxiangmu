from __future__ import annotations

from db import fetch_all


def low_mastery_cards(limit: int = 10) -> list[dict]:
    return fetch_all(
        """
        SELECT id, subject, topic, mastery, core_question
        FROM knowledge_cards
        WHERE mastery < 70
        ORDER BY mastery ASC, created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def recent_blockers(limit: int = 8) -> list[dict]:
    return fetch_all(
        """
        SELECT id, date, subject, title, blockers, mastery
        FROM study_sessions
        WHERE TRIM(blockers) != ''
        ORDER BY date DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )


def open_parking_questions(limit: int = 10) -> list[dict]:
    return fetch_all(
        """
        SELECT id, subject, question, source, status, created_at
        FROM parking_lot
        WHERE status != '已解决'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def recent_knowledge_links(limit: int = 8) -> list[dict]:
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
        JOIN knowledge_cards source ON source.id = kl.source_knowledge_id
        JOIN knowledge_cards target ON target.id = kl.target_knowledge_id
        ORDER BY kl.created_at DESC, kl.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def mistake_cause_counts(subject: str | None = None) -> list[dict]:
    params: tuple = ()
    where_clause = ""
    if subject:
        where_clause = "WHERE subject = ?"
        params = (subject,)
    return fetch_all(
        f"""
        SELECT cause_category, COUNT(*) AS count
        FROM mistakes
        {where_clause}
        GROUP BY cause_category
        ORDER BY count DESC, cause_category ASC
        """,
        params,
    )
