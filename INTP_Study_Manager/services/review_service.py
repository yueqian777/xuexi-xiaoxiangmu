from __future__ import annotations

from datetime import date, datetime, timedelta

from db import execute_many, fetch_all, fetch_one, insert_and_get_id, managed_connection
from models import REVIEW_INTERVALS
from services.auth_service import require_login
from services.mastery_service import apply_review_result


def _to_date(value: str | date | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value[:10]).date()


def create_initial_review_tasks(knowledge_id: int, start_date: str | date | None = None, *, user_id: int | None = None) -> None:
    user_id = user_id if user_id is not None else require_login().id
    base_date = _to_date(start_date)
    rows = [
        (user_id, knowledge_id, (base_date + timedelta(days=days)).isoformat(), stage)
        for days, stage in REVIEW_INTERVALS
    ]
    execute_many(
        """
        INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )


def ensure_initial_review_tasks(knowledge_id: int, start_date: str | date | None = None, *, user_id: int | None = None) -> None:
    user_id = user_id if user_id is not None else require_login().id
    existing = fetch_one(
        "SELECT COUNT(*) AS count FROM review_tasks WHERE knowledge_id = ? AND user_id = ?",
        (knowledge_id, user_id),
    )
    if not existing or existing["count"] == 0:
        create_initial_review_tasks(knowledge_id, start_date, user_id=user_id)


def get_review_tasks(where_clause: str = "", params: tuple = (), *, user_id: int | None = None) -> list[dict]:
    user_id = user_id if user_id is not None else require_login().id
    base_where = "WHERE rt.user_id = ?"
    base_params = [user_id]
    if where_clause:
        if where_clause.strip().upper().startswith("WHERE"):
            base_where += " AND " + where_clause.strip()[5:].strip()
        else:
            base_where += " AND " + where_clause
    base_params.extend(params)
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
                WHERE m.user_id = rt.user_id AND (m.knowledge_id = kc.id OR (m.subject = kc.subject AND m.topic = kc.topic))
                ORDER BY m.created_at DESC
                LIMIT 1
            ) AS last_cause
        FROM review_tasks rt
        JOIN knowledge_cards kc ON kc.id = rt.knowledge_id AND kc.user_id = rt.user_id
        {base_where}
        ORDER BY rt.review_date ASC, rt.id ASC
        """,
        tuple(base_params),
    )


def get_today_review_tasks(*, user_id: int | None = None) -> list[dict]:
    today = date.today().isoformat()
    return get_review_tasks(
        "WHERE rt.review_date <= ? AND rt.status = '待复习'",
        (today,),
        user_id=user_id,
    )


def get_all_pending_review_tasks(*, user_id: int | None = None) -> list[dict]:
    return get_review_tasks("WHERE rt.status = '待复习'", user_id=user_id)


def mark_review_result(task_id: int, result: str) -> None:
    user = require_login()
    task = fetch_one(
        """
        SELECT rt.*, kc.mastery
        FROM review_tasks rt
        JOIN knowledge_cards kc ON kc.id = rt.knowledge_id AND kc.user_id = rt.user_id
        WHERE rt.id = ? AND rt.user_id = ?
        """,
        (task_id, user.id),
    )
    if not task:
        return

    new_mastery = apply_review_result(int(task["mastery"]), result)
    with managed_connection() as conn:
        conn.execute(
            "UPDATE review_tasks SET status = '已完成', result = ? WHERE id = ? AND user_id = ?",
            (result, task_id, user.id),
        )
        conn.execute(
            "UPDATE knowledge_cards SET mastery = ? WHERE id = ? AND user_id = ?",
            (new_mastery, task["knowledge_id"], user.id),
        )

    if result == "仍然模糊":
        _create_extra_review(task["knowledge_id"], 2, "追加复习：2 天后", user_id=user.id)
    elif result == "完全不会":
        _create_extra_review(task["knowledge_id"], 1, "重点突破：1 天后", user_id=user.id)


def _create_extra_review(knowledge_id: int, days: int, stage: str, *, user_id: int) -> None:
    review_date = (date.today() + timedelta(days=days)).isoformat()
    insert_and_get_id(
        """
        INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, knowledge_id, review_date, stage),
    )
