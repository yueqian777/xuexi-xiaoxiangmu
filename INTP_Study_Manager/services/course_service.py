from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import db
from repositories import course_repository
from services.active_learning_context_service import get_active_context


COURSE_STATUSES = frozenset({"active", "completed", "archived"})
MAX_COURSE_NAME_LENGTH = 120


def create_course(user_id: int, name: str) -> dict[str, Any]:
    owner_id = _non_negative_int(user_id, "user_id")
    course_name = _course_name(name)
    db.init_db()
    with db.write_transaction() as conn:
        existing = course_repository.fetch_active_course_by_name(
            conn,
            owner_id,
            course_name,
        )
        if existing is not None:
            raise ValueError(f"课程「{course_name}」正在学习中。")
        return course_repository.insert_course(conn, owner_id, course_name)


def ensure_course_for_subject(
    user_id: int,
    subject: str,
    *,
    conn=None,
) -> int | None:
    """Return an owned course for a subject, creating an active one if absent.

    Write paths can pass their current SQLite connection so course association
    remains in the caller's transaction.  Existing completed or archived
    courses are deliberately not reactivated by this linking helper.
    """

    owner_id = _non_negative_int(user_id, "user_id")
    subject_name = str(subject or "").strip()
    if not subject_name:
        return None
    subject_name = _course_name(subject_name)

    if conn is not None:
        return _ensure_course_for_subject_in_connection(conn, owner_id, subject_name)

    db.init_db()
    with db.write_transaction() as write_conn:
        return _ensure_course_for_subject_in_connection(
            write_conn,
            owner_id,
            subject_name,
        )


def get_course(user_id: int, course_id: int) -> dict[str, Any] | None:
    owner_id = _non_negative_int(user_id, "user_id")
    owned_course_id = _positive_int(course_id, "course_id")
    db.init_db()
    with db.managed_connection() as conn:
        return course_repository.fetch_course(conn, owner_id, owned_course_id)


def list_courses(
    user_id: int,
    statuses: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    owner_id = _non_negative_int(user_id, "user_id")
    normalized_statuses = _statuses(statuses)
    db.init_db()
    with db.managed_connection() as conn:
        return course_repository.list_courses(conn, owner_id, normalized_statuses)


def complete_course(user_id: int, course_id: int) -> dict[str, Any] | None:
    owner_id = _non_negative_int(user_id, "user_id")
    owned_course_id = _positive_int(course_id, "course_id")
    db.init_db()
    with db.write_transaction() as conn:
        course = course_repository.fetch_course(conn, owner_id, owned_course_id)
        if course is None:
            return None
        if course["status"] == "archived":
            raise ValueError("归档课程必须先重新激活，才能完成新的学习阶段。")
        phase_id = None
        if course["status"] != "completed":
            course_repository.set_course_status(conn, owner_id, owned_course_id, "completed")
            phase_id = course_repository.close_open_learning_phase(
                conn,
                owner_id,
                owned_course_id,
                "completed",
            )
        completed = course_repository.fetch_course(conn, owner_id, owned_course_id)
        if completed is None:  # pragma: no cover - guarded by the owned read above
            return None
        summary = course_repository.build_course_summary(conn, owner_id, completed)
        course_repository.save_course_summary(
            conn,
            owner_id,
            owned_course_id,
            summary,
            phase_id=phase_id,
        )
        return course_repository.fetch_course(conn, owner_id, owned_course_id)


def archive_course(user_id: int, course_id: int) -> dict[str, Any] | None:
    owner_id = _non_negative_int(user_id, "user_id")
    owned_course_id = _positive_int(course_id, "course_id")
    db.init_db()
    with db.write_transaction() as conn:
        course = course_repository.fetch_course(conn, owner_id, owned_course_id)
        if course is None:
            return None
        phase_id = None
        if course["status"] != "archived":
            course_repository.set_course_status(conn, owner_id, owned_course_id, "archived")
            phase_id = course_repository.close_open_learning_phase(
                conn,
                owner_id,
                owned_course_id,
                "archived",
            )
        archived = course_repository.fetch_course(conn, owner_id, owned_course_id)
        if archived is None:  # pragma: no cover - guarded by the owned read above
            return None
        summary = course_repository.build_course_summary(conn, owner_id, archived)
        course_repository.save_course_summary(
            conn,
            owner_id,
            owned_course_id,
            summary,
            phase_id=phase_id,
        )
        return course_repository.fetch_course(conn, owner_id, owned_course_id)


def reactivate_course(user_id: int, course_id: int) -> dict[str, Any] | None:
    owner_id = _non_negative_int(user_id, "user_id")
    owned_course_id = _positive_int(course_id, "course_id")
    db.init_db()
    with db.write_transaction() as conn:
        course = course_repository.fetch_course(conn, owner_id, owned_course_id)
        if course is None:
            return None
        if course["status"] == "active":
            return course
        same_named_active = course_repository.fetch_active_course_by_name(
            conn,
            owner_id,
            str(course["name"]),
        )
        if same_named_active is not None and int(same_named_active["id"]) != owned_course_id:
            raise ValueError("已有同名课程正在学习；请先结束当前课程，再重新激活历史阶段。")
        course_repository.set_course_status(conn, owner_id, owned_course_id, "active")
        course_repository.append_learning_phase(conn, owner_id, owned_course_id)
        return course_repository.fetch_course(conn, owner_id, owned_course_id)


def get_course_summary(user_id: int, course_id: int) -> dict[str, Any] | None:
    owner_id = _non_negative_int(user_id, "user_id")
    owned_course_id = _positive_int(course_id, "course_id")
    db.init_db()
    with db.managed_connection() as conn:
        if course_repository.fetch_course(conn, owner_id, owned_course_id) is None:
            return None
        return course_repository.fetch_course_summary(conn, owner_id, owned_course_id)


def get_dashboard_snapshot(user_id: int) -> dict[str, Any]:
    owner_id = _non_negative_int(user_id, "user_id")
    db.init_db()
    active_context = get_active_context(owner_id)
    with db.managed_connection() as conn:
        active_courses = course_repository.list_courses(conn, owner_id, ["active"])
        current_course = active_courses[0] if active_courses else None
        context_deck_id = (
            int(active_context.get("deck_id") or 0)
            if active_context.get("active")
            else 0
        )
        if context_deck_id:
            context_course = course_repository.fetch_active_course_for_deck(
                conn,
                owner_id,
                context_deck_id,
            )
            if context_course is not None:
                current_course = context_course
        return {
            "current_course": current_course,
            "active_courses": active_courses,
            "status_counts": course_repository.status_counts(conn, owner_id),
        }


def get_course_detail(user_id: int, course_id: int) -> dict[str, Any] | None:
    owner_id = _non_negative_int(user_id, "user_id")
    owned_course_id = _positive_int(course_id, "course_id")
    db.init_db()
    with db.managed_connection() as conn:
        course = course_repository.fetch_course(conn, owner_id, owned_course_id)
        if course is None:
            return None
        return {
            "course": course,
            "summary": course_repository.fetch_course_summary(
                conn,
                owner_id,
                owned_course_id,
            ),
            "learning_phases": course_repository.list_learning_phases(
                conn,
                owner_id,
                owned_course_id,
            ),
            "decks": course_repository.list_course_decks(
                conn,
                owner_id,
                owned_course_id,
            ),
        }


def _course_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("课程名称不能为空。")
    name = value.strip()
    if not name:
        raise ValueError("课程名称不能为空。")
    if len(name) > MAX_COURSE_NAME_LENGTH:
        raise ValueError(f"课程名称不能超过 {MAX_COURSE_NAME_LENGTH} 个字符。")
    return name


def _ensure_course_for_subject_in_connection(conn, user_id: int, name: str) -> int:
    course = course_repository.fetch_active_course_by_name(conn, user_id, name)
    if course is None:
        course = course_repository.insert_course(conn, user_id, name)
    return int(course["id"])


def _statuses(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, str):
        requested = [values]
    else:
        requested = list(values)
    normalized: list[str] = []
    for value in requested:
        status = str(value or "").strip()
        if status not in COURSE_STATUSES:
            raise ValueError("课程状态必须是 active、completed 或 archived。")
        if status not in normalized:
            normalized.append(status)
    return normalized


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} 必须是非负整数。")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{label} 必须是非负整数。")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是非负整数。") from exc
    if parsed < 0:
        raise ValueError(f"{label} 必须是非负整数。")
    return parsed


def _positive_int(value: object, label: str) -> int:
    parsed = _non_negative_int(value, label)
    if parsed <= 0:
        raise ValueError(f"{label} 必须是正整数。")
    return parsed
