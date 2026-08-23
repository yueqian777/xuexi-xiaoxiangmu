from __future__ import annotations

import json
from typing import Any, Iterable


COURSE_COLUMNS = """
    id, user_id, name, status, completed_at, archived_at,
    course_summary, created_at, updated_at
"""


def insert_course(conn, user_id: int, name: str) -> dict[str, Any]:
    cursor = conn.execute(
        """
        INSERT INTO courses (user_id, name, status)
        VALUES (?, ?, 'active')
        """,
        (user_id, name),
    )
    course_id = int(cursor.lastrowid)
    append_learning_phase(conn, user_id, course_id)
    course = fetch_course(conn, user_id, course_id)
    if course is None:  # pragma: no cover - the insert and read share one transaction
        raise RuntimeError("课程创建后无法读取。")
    return course


def fetch_course(conn, user_id: int, course_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT {COURSE_COLUMNS}
        FROM courses
        WHERE user_id = ? AND id = ?
        """,
        (user_id, course_id),
    ).fetchone()
    return dict(row) if row else None


def fetch_course_by_name(conn, user_id: int, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT {COURSE_COLUMNS}
        FROM courses
        WHERE user_id = ? AND TRIM(name) = ?
        ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'completed' THEN 1 ELSE 2 END,
                 updated_at DESC,
                 id DESC
        LIMIT 1
        """,
        (user_id, name),
    ).fetchone()
    return dict(row) if row else None


def fetch_active_course_by_name(conn, user_id: int, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT {COURSE_COLUMNS}
        FROM courses
        WHERE user_id = ? AND TRIM(name) = ? AND status = 'active'
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, name),
    ).fetchone()
    return dict(row) if row else None


def fetch_active_course_for_deck(
    conn,
    user_id: int,
    deck_id: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            course.id, course.user_id, course.name, course.status,
            course.completed_at, course.archived_at, course.course_summary,
            course.created_at, course.updated_at
        FROM ppt_decks AS deck
        JOIN courses AS course
          ON course.id = deck.course_id
         AND course.user_id = deck.user_id
        WHERE deck.user_id = ? AND deck.id = ? AND course.status = 'active'
        LIMIT 1
        """,
        (user_id, deck_id),
    ).fetchone()
    return dict(row) if row else None


def list_courses(
    conn,
    user_id: int,
    statuses: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [user_id]
    status_clause = ""
    if statuses is not None:
        status_values = list(statuses)
        if not status_values:
            return []
        placeholders = ", ".join("?" for _ in status_values)
        status_clause = f" AND status IN ({placeholders})"
        params.extend(status_values)
    rows = conn.execute(
        f"""
        SELECT {COURSE_COLUMNS}
        FROM courses
        WHERE user_id = ?{status_clause}
        ORDER BY updated_at DESC, id DESC
        """,
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def set_course_status(
    conn,
    user_id: int,
    course_id: int,
    status: str,
) -> bool:
    if status == "completed":
        cursor = conn.execute(
            """
            UPDATE courses
            SET status = 'completed',
                completed_at = datetime('now', 'localtime'),
                archived_at = NULL,
                updated_at = datetime('now', 'localtime')
            WHERE user_id = ? AND id = ?
            """,
            (user_id, course_id),
        )
    elif status == "archived":
        cursor = conn.execute(
            """
            UPDATE courses
            SET status = 'archived',
                archived_at = datetime('now', 'localtime'),
                updated_at = datetime('now', 'localtime')
            WHERE user_id = ? AND id = ?
            """,
            (user_id, course_id),
        )
    elif status == "active":
        cursor = conn.execute(
            """
            UPDATE courses
            SET status = 'active',
                completed_at = NULL,
                archived_at = NULL,
                updated_at = datetime('now', 'localtime')
            WHERE user_id = ? AND id = ?
            """,
            (user_id, course_id),
        )
    else:  # pragma: no cover - service validation owns this boundary
        raise ValueError("未知课程状态。")
    return int(cursor.rowcount or 0) == 1


def append_learning_phase(conn, user_id: int, course_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(phase_number), 0) + 1 AS next_number
        FROM course_learning_phases
        WHERE user_id = ? AND course_id = ?
        """,
        (user_id, course_id),
    ).fetchone()
    phase_number = int(row["next_number"] or 1)
    cursor = conn.execute(
        """
        INSERT INTO course_learning_phases (user_id, course_id, phase_number)
        VALUES (?, ?, ?)
        """,
        (user_id, course_id, phase_number),
    )
    phase = conn.execute(
        """
        SELECT id, user_id, course_id, phase_number, started_at, ended_at,
               outcome, course_summary, created_at
        FROM course_learning_phases
        WHERE id = ? AND user_id = ?
        """,
        (int(cursor.lastrowid), user_id),
    ).fetchone()
    return dict(phase)


def close_open_learning_phase(
    conn,
    user_id: int,
    course_id: int,
    outcome: str,
) -> int | None:
    phase = conn.execute(
        """
        SELECT id
        FROM course_learning_phases
        WHERE user_id = ? AND course_id = ? AND ended_at IS NULL
        ORDER BY phase_number DESC, id DESC
        LIMIT 1
        """,
        (user_id, course_id),
    ).fetchone()
    if not phase:
        return None
    phase_id = int(phase["id"])
    cursor = conn.execute(
        """
        UPDATE course_learning_phases
        SET ended_at = datetime('now', 'localtime'), outcome = ?
        WHERE id = ? AND user_id = ? AND course_id = ? AND ended_at IS NULL
        """,
        (outcome, phase_id, user_id, course_id),
    )
    return phase_id if int(cursor.rowcount or 0) == 1 else None


def list_learning_phases(conn, user_id: int, course_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, user_id, course_id, phase_number, started_at, ended_at,
               outcome, course_summary, created_at
        FROM course_learning_phases
        WHERE user_id = ? AND course_id = ?
        ORDER BY phase_number ASC, id ASC
        """,
        (user_id, course_id),
    ).fetchall()
    return [dict(row) for row in rows]


def list_course_decks(conn, user_id: int, course_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, user_id, course_id, filename, title, subject, category,
               sort_order, status, file_path, slide_count, created_at
        FROM ppt_decks
        WHERE user_id = ? AND course_id = ?
        ORDER BY sort_order ASC, created_at DESC, id DESC
        """,
        (user_id, course_id),
    ).fetchall()
    return [dict(row) for row in rows]


def build_course_summary(
    conn,
    user_id: int,
    course: dict[str, Any],
) -> dict[str, Any]:
    course_id = int(course["id"])
    deck_count = _count(
        conn,
        "SELECT COUNT(*) AS count FROM ppt_decks WHERE user_id = ? AND course_id = ?",
        (user_id, course_id),
    )
    slide_count = _count(
        conn,
        """
        SELECT COUNT(*) AS count
        FROM ppt_slides AS slide
        WHERE slide.user_id = ?
          AND EXISTS (
              SELECT 1
              FROM ppt_decks AS deck
              WHERE deck.id = slide.deck_id
                AND deck.user_id = ?
                AND deck.course_id = ?
          )
        """,
        (user_id, user_id, course_id),
    )
    question_count = _count(
        conn,
        """
        SELECT COUNT(*) AS count
        FROM slide_questions AS question
        WHERE question.user_id = ?
          AND EXISTS (
              SELECT 1
              FROM ppt_slides AS slide
              JOIN ppt_decks AS deck ON deck.id = slide.deck_id
              WHERE slide.id = question.slide_id
                AND slide.user_id = ?
                AND deck.user_id = ?
                AND deck.course_id = ?
          )
        """,
        (user_id, user_id, user_id, course_id),
    )
    knowledge_count = _count(
        conn,
        """
        SELECT COUNT(*) AS count
        FROM knowledge_cards
        WHERE user_id = ? AND course_id = ?
        """,
        (user_id, course_id),
    )
    review_counts = conn.execute(
        """
        SELECT
            COUNT(*) AS review_count,
            COALESCE(SUM(CASE WHEN task.status = '已完成' THEN 1 ELSE 0 END), 0)
                AS completed_review_count,
            COALESCE(SUM(CASE WHEN task.status != '已完成' THEN 1 ELSE 0 END), 0)
                AS pending_review_count
        FROM review_tasks AS task
        WHERE task.user_id = ?
          AND EXISTS (
              SELECT 1
              FROM knowledge_cards AS card
              WHERE card.id = task.knowledge_id
                AND card.user_id = ?
                AND card.course_id = ?
          )
        """,
        (user_id, user_id, course_id),
    ).fetchone()
    review_count = int(review_counts["review_count"] or 0)
    completed_review_count = int(review_counts["completed_review_count"] or 0)
    pending_review_count = int(review_counts["pending_review_count"] or 0)

    weak_points = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id AS knowledge_id, topic, mastery
            FROM knowledge_cards
            WHERE user_id = ? AND course_id = ? AND mastery < 70
            ORDER BY mastery ASC, id ASC
            """,
            (user_id, course_id),
        ).fetchall()
    ]
    core_knowledge = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id AS knowledge_id, topic, mastery
            FROM knowledge_cards
            WHERE user_id = ? AND course_id = ? AND mastery >= 70
            ORDER BY mastery DESC, id ASC
            """,
            (user_id, course_id),
        ).fetchall()
    ]
    session_count = _count(
        conn,
        """
        SELECT COUNT(*) AS count
        FROM study_sessions
        WHERE user_id = ? AND course_id = ?
        """,
        (user_id, course_id),
    )
    activity_range = _course_activity_range(conn, user_id, course_id)
    advice = _future_review_advice(pending_review_count, len(weak_points))
    summary = {
        "course_id": course_id,
        "name": str(course.get("name") or ""),
        "status": str(course.get("status") or ""),
        "started_at": activity_range["started_at"] or str(course.get("created_at") or ""),
        "last_activity_at": activity_range["last_activity_at"] or str(course.get("created_at") or ""),
        "completed_at": course.get("completed_at"),
        "archived_at": course.get("archived_at"),
        "deck_count": deck_count,
        "slide_count": slide_count,
        "question_count": question_count,
        "knowledge_count": knowledge_count,
        "review_count": review_count,
        "completed_review_count": completed_review_count,
        "pending_review_count": pending_review_count,
        "review_total": review_count,
        "review_completed": completed_review_count,
        "review_pending": pending_review_count,
        "study_session_count": session_count,
        "core_knowledge": core_knowledge,
        "weak_points": weak_points,
        "weak_knowledge": weak_points,
        "future_review_advice": advice,
        "future_review_suggestion": advice,
    }
    return summary


def save_course_summary(
    conn,
    user_id: int,
    course_id: int,
    summary: dict[str, Any],
    *,
    phase_id: int | None = None,
) -> None:
    payload = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    weak_points_json = json.dumps(summary["weak_points"], ensure_ascii=False)
    core_knowledge_json = json.dumps(summary["core_knowledge"], ensure_ascii=False)
    existing = conn.execute(
        """
        SELECT id
        FROM course_summaries
        WHERE user_id = ? AND course_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, course_id),
    ).fetchone()
    values = (
        int(summary["deck_count"]),
        int(summary["slide_count"]),
        int(summary["question_count"]),
        int(summary["knowledge_count"]),
        int(summary["review_count"]),
        int(summary["completed_review_count"]),
        int(summary["pending_review_count"]),
        weak_points_json,
        core_knowledge_json,
        str(summary["future_review_advice"]),
        payload,
    )
    if existing:
        conn.execute(
            """
            UPDATE course_summaries
            SET deck_count = ?, slide_count = ?, question_count = ?,
                knowledge_count = ?, review_count = ?, completed_review_count = ?,
                pending_review_count = ?, weak_points_json = ?,
                core_knowledge_json = ?, future_review_advice = ?, summary_json = ?,
                updated_at = datetime('now', 'localtime')
            WHERE id = ? AND user_id = ? AND course_id = ?
            """,
            (*values, int(existing["id"]), user_id, course_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO course_summaries (
                user_id, course_id, deck_count, slide_count, question_count,
                knowledge_count, review_count, completed_review_count,
                pending_review_count, weak_points_json, core_knowledge_json,
                future_review_advice, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, course_id, *values),
        )
    conn.execute(
        """
        UPDATE courses
        SET course_summary = ?, updated_at = datetime('now', 'localtime')
        WHERE id = ? AND user_id = ?
        """,
        (payload, course_id, user_id),
    )
    if phase_id is not None:
        conn.execute(
            """
            UPDATE course_learning_phases
            SET course_summary = ?
            WHERE id = ? AND user_id = ? AND course_id = ?
            """,
            (payload, phase_id, user_id, course_id),
        )


def fetch_course_summary(conn, user_id: int, course_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT deck_count, slide_count, question_count, knowledge_count,
               review_count, completed_review_count, pending_review_count,
               weak_points_json, core_knowledge_json, future_review_advice,
               summary_json
        FROM course_summaries
        WHERE user_id = ? AND course_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, course_id),
    ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["summary_json"] or "")
    except (TypeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and payload:
        return payload

    course = fetch_course(conn, user_id, course_id)
    if course is None:
        return None
    weak_points = _json_list(row["weak_points_json"])
    core_knowledge = _json_list(row["core_knowledge_json"])
    review_count = int(row["review_count"] or 0)
    completed_review_count = int(row["completed_review_count"] or 0)
    pending_review_count = int(row["pending_review_count"] or 0)
    advice = str(row["future_review_advice"] or "")
    return {
        "course_id": course_id,
        "name": course["name"],
        "status": course["status"],
        "started_at": course["created_at"],
        "completed_at": course["completed_at"],
        "archived_at": course["archived_at"],
        "deck_count": int(row["deck_count"] or 0),
        "slide_count": int(row["slide_count"] or 0),
        "question_count": int(row["question_count"] or 0),
        "knowledge_count": int(row["knowledge_count"] or 0),
        "review_count": review_count,
        "completed_review_count": completed_review_count,
        "pending_review_count": pending_review_count,
        "review_total": review_count,
        "review_completed": completed_review_count,
        "review_pending": pending_review_count,
        "core_knowledge": core_knowledge,
        "weak_points": weak_points,
        "weak_knowledge": weak_points,
        "future_review_advice": advice,
        "future_review_suggestion": advice,
    }


def status_counts(conn, user_id: int) -> dict[str, int]:
    counts = {"active": 0, "completed": 0, "archived": 0}
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM courses
        WHERE user_id = ?
        GROUP BY status
        """,
        (user_id,),
    ).fetchall()
    for row in rows:
        status = str(row["status"] or "")
        if status in counts:
            counts[status] = int(row["count"] or 0)
    return counts


def _count(conn, query: str, params: tuple[Any, ...]) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row["count"] or 0)


def _course_activity_range(conn, user_id: int, course_id: int) -> dict[str, str]:
    """Return real recorded activity bounds without inventing study duration."""

    row = conn.execute(
        """
        SELECT MIN(activity_at) AS started_at, MAX(activity_at) AS last_activity_at
        FROM (
            SELECT date AS activity_at
            FROM study_sessions
            WHERE user_id = ? AND course_id = ?

            UNION ALL

            SELECT created_at AS activity_at
            FROM ppt_decks
            WHERE user_id = ? AND course_id = ?

            UNION ALL

            SELECT created_at AS activity_at
            FROM knowledge_cards
            WHERE user_id = ? AND course_id = ?

            UNION ALL

            SELECT question.created_at AS activity_at
            FROM slide_questions AS question
            JOIN ppt_slides AS slide
              ON slide.id = question.slide_id
             AND slide.user_id = question.user_id
            JOIN ppt_decks AS deck
              ON deck.id = slide.deck_id
             AND deck.user_id = slide.user_id
            WHERE question.user_id = ? AND deck.course_id = ?
        )
        WHERE TRIM(COALESCE(activity_at, '')) != ''
        """,
        (
            user_id,
            course_id,
            user_id,
            course_id,
            user_id,
            course_id,
            user_id,
            course_id,
        ),
    ).fetchone()
    return {
        "started_at": str(row["started_at"] or "") if row else "",
        "last_activity_at": str(row["last_activity_at"] or "") if row else "",
    }


def _json_list(value: object) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _future_review_advice(pending_count: int, weak_count: int) -> str:
    if pending_count and weak_count:
        return f"优先完成 {pending_count} 个待复习任务，并在一个月后复习 {weak_count} 个薄弱知识点。"
    if pending_count:
        return f"优先完成 {pending_count} 个待复习任务，完成后安排一次整课复习。"
    if weak_count:
        return f"针对 {weak_count} 个薄弱知识点进行闭卷回忆，并在一个月后复习。"
    return "当前复习任务已完成，建议一个月后进行一次整课复习。"
