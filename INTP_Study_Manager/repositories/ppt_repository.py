from __future__ import annotations

from db import fetch_all, fetch_one, insert_and_get_id


def add_slide_explanation(user_id: int, slide_id: int, model: str, explanation: str) -> int:
    return insert_and_get_id(
        """
        INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
        VALUES (?, ?, ?, ?)
        """,
        (int(user_id), int(slide_id), model, explanation),
    )


def latest_explanation(user_id: int, slide_id: int) -> dict | None:
    return fetch_one(
        """
        SELECT *
        FROM slide_explanations
        WHERE user_id = ? AND slide_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (int(user_id), int(slide_id)),
    )


def latest_explanations_by_slide_ids(user_id: int, slide_ids: list[int]) -> dict[int, dict]:
    if not slide_ids:
        return {}
    latest: dict[int, dict] = {}
    chunk_size = 900
    for start in range(0, len(slide_ids), chunk_size):
        chunk = [int(slide_id) for slide_id in slide_ids[start : start + chunk_size]]
        placeholders = ",".join("?" for _ in chunk)
        rows = fetch_all(
            f"""
            SELECT id, slide_id, model, explanation, created_at
            FROM (
                SELECT
                    se.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY se.slide_id
                        ORDER BY se.created_at DESC, se.id DESC
                    ) AS rn
                FROM slide_explanations se
                WHERE se.user_id = ? AND se.slide_id IN ({placeholders})
            )
            WHERE rn = 1
            """,
            (int(user_id), *tuple(chunk)),
        )
        latest.update({int(row["slide_id"]): row for row in rows})
    return latest


def add_slide_question(user_id: int, slide_id: int, question: str, answer: str, model: str) -> int:
    return insert_and_get_id(
        """
        INSERT INTO slide_questions (user_id, slide_id, question, answer, model)
        VALUES (?, ?, ?, ?, ?)
        """,
        (int(user_id), int(slide_id), question, answer, model),
    )


def questions_by_slide_ids(user_id: int, slide_ids: list[int]) -> dict[int, list[dict]]:
    if not slide_ids:
        return {}
    grouped: dict[int, list[dict]] = {int(slide_id): [] for slide_id in slide_ids}
    chunk_size = 900
    for start in range(0, len(slide_ids), chunk_size):
        chunk = [int(slide_id) for slide_id in slide_ids[start : start + chunk_size]]
        placeholders = ",".join("?" for _ in chunk)
        rows = fetch_all(
            f"""
            SELECT slide_id, question, answer, model, category, status, sort_order, created_at
            FROM slide_questions
            WHERE user_id = ? AND slide_id IN ({placeholders})
            ORDER BY sort_order ASC, created_at ASC, id ASC
            """,
            (int(user_id), *tuple(chunk)),
        )
        for row in rows:
            grouped.setdefault(int(row["slide_id"]), []).append(row)
    return grouped
