from __future__ import annotations

from datetime import date, datetime, timedelta

from db import fetch_all, write_transaction
from models import REVIEW_INTERVALS, REVIEW_RESULTS
from services.auth_service import require_login
from services.mastery_service import apply_review_result


def _to_date(value: str | date | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value[:10]).date()


def create_initial_review_tasks(
    knowledge_id: int,
    start_date: str | date | None = None,
    *,
    user_id: int | None = None,
    conn=None,
) -> None:
    user_id = user_id if user_id is not None else require_login().id
    base_date = _to_date(start_date)
    rows = [
        (user_id, knowledge_id, (base_date + timedelta(days=days)).isoformat(), stage)
        for days, stage in REVIEW_INTERVALS
    ]
    _insert_review_tasks_if_missing(rows, conn=conn)


def ensure_initial_review_tasks(
    knowledge_id: int,
    start_date: str | date | None = None,
    *,
    user_id: int | None = None,
    conn=None,
) -> None:
    owner_id = user_id if user_id is not None else require_login().id
    requested_base_date = _to_date(start_date)
    if conn is None:
        with write_transaction() as write_conn:
            _ensure_initial_review_tasks(
                write_conn,
                int(owner_id),
                int(knowledge_id),
                requested_base_date,
            )
        return
    _ensure_initial_review_tasks(
        conn,
        int(owner_id),
        int(knowledge_id),
        requested_base_date,
    )


def _ensure_initial_review_tasks(
    conn,
    user_id: int,
    knowledge_id: int,
    requested_base_date: date,
) -> None:
    base_date = _existing_initial_review_base_date(
        conn,
        user_id,
        knowledge_id,
    ) or requested_base_date
    create_initial_review_tasks(
        knowledge_id,
        base_date,
        user_id=user_id,
        conn=conn,
    )


def _existing_initial_review_base_date(conn, user_id: int, knowledge_id: int) -> date | None:
    stage_offsets = {stage: days for days, stage in REVIEW_INTERVALS}
    rows = conn.execute(
        """
        SELECT review_date, review_stage
        FROM review_tasks
        WHERE user_id = ? AND knowledge_id = ?
        ORDER BY id ASC
        """,
        (user_id, knowledge_id),
    ).fetchall()
    for row in rows:
        days = stage_offsets.get(row["review_stage"])
        if days is None:
            continue
        try:
            return _to_date(row["review_date"]) - timedelta(days=days)
        except (TypeError, ValueError):
            continue
    return None


def get_review_tasks(
    where_clause: str = "",
    params: tuple = (),
    *,
    user_id: int | None = None,
    include_archived: bool = False,
) -> list[dict]:
    user_id = user_id if user_id is not None else require_login().id
    base_where = "WHERE rt.user_id = ?"
    base_params = [user_id]
    if not include_archived:
        base_where += " AND COALESCE(course.status, 'active') <> 'archived'"
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
        LEFT JOIN courses course ON course.id = kc.course_id AND course.user_id = kc.user_id
        {base_where}
        ORDER BY rt.review_date ASC, rt.id ASC
        """,
        tuple(base_params),
    )


def get_today_review_tasks(
    *,
    user_id: int | None = None,
    include_archived: bool = False,
) -> list[dict]:
    today = date.today().isoformat()
    return get_review_tasks(
        "WHERE rt.review_date <= ? AND rt.status = '待复习'",
        (today,),
        user_id=user_id,
        include_archived=include_archived,
    )


def get_all_pending_review_tasks(
    *,
    user_id: int | None = None,
    include_archived: bool = False,
) -> list[dict]:
    return get_review_tasks(
        "WHERE rt.status = '待复习'",
        user_id=user_id,
        include_archived=include_archived,
    )


def submit_review_result(user_id: int, task_id: int, result: str) -> dict | None:
    """Complete one owned pending review and update mastery atomically.

    ``None`` deliberately covers missing, foreign-owned, and already-completed
    tasks so callers cannot use this service as a cross-user existence oracle.
    """

    owner_id = _non_negative_int(user_id, "user_id")
    review_task_id = _positive_int(task_id, "task_id")
    clean_result = str(result or "").strip()
    if clean_result not in REVIEW_RESULTS:
        raise ValueError("result must be one of the configured review results")

    with write_transaction() as conn:
        task = conn.execute(
            """
            SELECT rt.*, kc.mastery
            FROM review_tasks rt
            JOIN knowledge_cards kc ON kc.id = rt.knowledge_id AND kc.user_id = rt.user_id
            WHERE rt.id = ? AND rt.user_id = ? AND rt.status = '待复习'
            """,
            (review_task_id, owner_id),
        ).fetchone()
        if not task:
            return None

        mastery_before = int(task["mastery"])
        new_mastery = apply_review_result(mastery_before, clean_result)
        updated = conn.execute(
            """
            UPDATE review_tasks
            SET status = '已完成', result = ?
            WHERE id = ? AND user_id = ? AND status = '待复习'
            """,
            (clean_result, review_task_id, owner_id),
        )
        if updated.rowcount != 1:
            return None
        conn.execute(
            "UPDATE knowledge_cards SET mastery = ? WHERE id = ? AND user_id = ?",
            (new_mastery, task["knowledge_id"], owner_id),
        )
        extra_review: dict | None = None
        extra_review_spec: tuple[int, str] | None = None
        if clean_result == "仍然模糊":
            extra_review_spec = (2, "追加复习：2 天后")
        elif clean_result == "完全不会":
            extra_review_spec = (1, "重点突破：1 天后")
        if extra_review_spec:
            days, stage = extra_review_spec
            review_date = (date.today() + timedelta(days=days)).isoformat()
            created = _insert_review_task_if_missing(
                conn,
                (owner_id, int(task["knowledge_id"]), review_date, stage),
            )
            extra_review = {
                "created": created,
                "review_date": review_date,
                "review_stage": stage,
            }
        return {
            "review_task_id": review_task_id,
            "knowledge_id": int(task["knowledge_id"]),
            "result": clean_result,
            "mastery_before": mastery_before,
            "mastery_after": new_mastery,
            "extra_review": extra_review,
        }


def mark_review_result(
    task_id: int,
    result: str,
    *,
    user_id: int | None = None,
) -> dict | None:
    """Backward-compatible UI entry point around explicit-user submission."""

    owner_id = user_id if user_id is not None else require_login().id
    return submit_review_result(owner_id, task_id, result)


def _create_extra_review(knowledge_id: int, days: int, stage: str, *, user_id: int) -> None:
    review_date = (date.today() + timedelta(days=days)).isoformat()
    _insert_review_tasks_if_missing([(user_id, knowledge_id, review_date, stage)])


def _insert_review_tasks_if_missing(rows: list[tuple[int, int, str, str]], *, conn=None) -> None:
    if not rows:
        return
    if conn is not None:
        for row in rows:
            _insert_review_task_if_missing(conn, row)
        return
    with write_transaction() as write_conn:
        for row in rows:
            _insert_review_task_if_missing(write_conn, row)


def _insert_review_task_if_missing(conn, row: tuple[int, int, str, str]) -> bool:
    user_id, knowledge_id, review_date, review_stage = row
    exists = conn.execute(
        """
        SELECT 1
        FROM review_tasks
        WHERE user_id = ? AND knowledge_id = ? AND review_date = ? AND review_stage = ?
        LIMIT 1
        """,
        (int(user_id), int(knowledge_id), review_date, review_stage),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        """
        INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
        VALUES (?, ?, ?, ?)
        """,
        (int(user_id), int(knowledge_id), review_date, review_stage),
    )
    return True


def _non_negative_int(value: object, label: str) -> int:
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


def _positive_int(value: object, label: str) -> int:
    parsed = _non_negative_int(value, label)
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed
