from __future__ import annotations

from datetime import date, datetime, timedelta

from db import execute, fetch_all, fetch_one, insert_and_get_id
from models import REVIEW_INTERVALS
from services.mastery_service import apply_review_result


def _to_date(value: str | date | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value[:10]).date()


def create_initial_review_tasks(knowledge_id: int, start_date: str | date | None = None) -> None:
    base_date = _to_date(start_date)
    for days, stage in REVIEW_INTERVALS:
        review_date = (base_date + timedelta(days=days)).isoformat()
        insert_and_get_id(
            """
            INSERT INTO review_tasks (knowledge_id, review_date, review_stage)
            VALUES (?, ?, ?)
            """,
            (knowledge_id, review_date, stage),
        )


def ensure_initial_review_tasks(knowledge_id: int, start_date: str | date | None = None) -> None:
    existing = fetch_one(
        "SELECT COUNT(*) AS count FROM review_tasks WHERE knowledge_id = ?",
        (knowledge_id,),
    )
    if not existing or existing["count"] == 0:
        create_initial_review_tasks(knowledge_id, start_date)


def get_review_tasks(where_clause: str = "", params: tuple = ()) -> list[dict]:
    return fetch_all(
        f"""
        SELECT
            rt.id,
            rt.knowledge_id,
            rt.review_date,
            rt.review_stage,
            rt.status,
            rt.result,
            kc.subject,
            kc.topic,
            kc.created_at AS original_learning_date,
            kc.mastery,
            (
                SELECT m.cause_category
                FROM mistakes m
                WHERE m.knowledge_id = kc.id OR (m.subject = kc.subject AND m.topic = kc.topic)
                ORDER BY m.created_at DESC
                LIMIT 1
            ) AS last_cause
        FROM review_tasks rt
        JOIN knowledge_cards kc ON kc.id = rt.knowledge_id
        {where_clause}
        ORDER BY rt.review_date ASC, rt.id ASC
        """,
        params,
    )


def get_today_review_tasks() -> list[dict]:
    today = date.today().isoformat()
    return get_review_tasks(
        "WHERE rt.review_date <= ? AND rt.status = '待复习'",
        (today,),
    )


def get_all_pending_review_tasks() -> list[dict]:
    return get_review_tasks("WHERE rt.status = '待复习'")


def mark_review_result(task_id: int, result: str) -> None:
    task = fetch_one(
        """
        SELECT rt.*, kc.mastery
        FROM review_tasks rt
        JOIN knowledge_cards kc ON kc.id = rt.knowledge_id
        WHERE rt.id = ?
        """,
        (task_id,),
    )
    if not task:
        return

    new_mastery = apply_review_result(int(task["mastery"]), result)
    execute(
        "UPDATE review_tasks SET status = '已完成', result = ? WHERE id = ?",
        (result, task_id),
    )
    execute(
        "UPDATE knowledge_cards SET mastery = ? WHERE id = ?",
        (new_mastery, task["knowledge_id"]),
    )

    if result == "仍然模糊":
        _create_extra_review(task["knowledge_id"], 2, "追加复习：2 天后")
    elif result == "完全不会":
        _create_extra_review(task["knowledge_id"], 1, "重点突破：1 天后")


def _create_extra_review(knowledge_id: int, days: int, stage: str) -> None:
    review_date = (date.today() + timedelta(days=days)).isoformat()
    insert_and_get_id(
        """
        INSERT INTO review_tasks (knowledge_id, review_date, review_stage)
        VALUES (?, ?, ?)
        """,
        (knowledge_id, review_date, stage),
    )

