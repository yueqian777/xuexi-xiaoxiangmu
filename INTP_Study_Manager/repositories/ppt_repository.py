from __future__ import annotations

from db import execute, fetch_all, fetch_one, insert_and_get_id, write_transaction


MAX_QUESTION_DEPTH = 5


def add_slide_explanation(user_id: int, slide_id: int, model: str, explanation: str) -> int:
    return insert_and_get_id(
        """
        INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
        VALUES (?, ?, ?, ?)
        """,
        (int(user_id), int(slide_id), model, explanation),
    )


def update_slide_learning_metadata(user_id: int, slide_id: int, *, title: str = "", page_type: str = "") -> None:
    assignments = []
    params = []
    if str(title or "").strip():
        assignments.append("title = ?")
        params.append(str(title).strip()[:80])
    if str(page_type or "").strip():
        assignments.append("page_type = ?")
        params.append(str(page_type).strip())
    if not assignments:
        return
    execute(
        f"""
        UPDATE ppt_slides
        SET {", ".join(assignments)}
        WHERE id = ? AND user_id = ?
        """,
        (*params, int(slide_id), int(user_id)),
    )


def update_slide_bookmark(
    user_id: int,
    slide_id: int,
    *,
    enabled: bool | None = None,
    title: str | None = None,
) -> None:
    assignments = []
    params = []
    if enabled is not None:
        assignments.append("bookmark_enabled = ?")
        params.append(1 if enabled else 0)
    if title is not None:
        assignments.append("bookmark_title = ?")
        params.append(str(title or "").strip()[:120])
    if not assignments:
        return
    execute(
        f"""
        UPDATE ppt_slides
        SET {", ".join(assignments)}
        WHERE id = ? AND user_id = ?
        """,
        (*params, int(slide_id), int(user_id)),
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


def add_slide_question(
    user_id: int,
    slide_id: int,
    question: str,
    answer: str,
    model: str,
    *,
    quote_text: str = "",
    root_question_id: int | str | None = None,
    parent_question_id: int | str | None = None,
    depth: int | str | None = None,
    quote_source: str = "slide",
    quote_source_question_id: int | str | None = None,
) -> int:
    user_id_int = int(user_id)
    slide_id_int = int(slide_id)
    parent_id = _optional_int(parent_question_id)
    requested_root_id = _optional_int(root_question_id)
    requested_depth = max(0, int(depth or 0))
    quote_source_question = _optional_int(quote_source_question_id)
    clean_quote_source = str(quote_source or "slide").strip() or "slide"

    with write_transaction() as conn:
        parent = None
        if parent_id is not None:
            parent = conn.execute(
                """
                SELECT id, slide_id, root_question_id, depth
                FROM slide_questions
                WHERE user_id = ? AND id = ?
                """,
                (user_id_int, parent_id),
            ).fetchone()
            if not parent or int(parent["slide_id"]) != slide_id_int:
                raise ValueError("parent question is not available for this slide")
            parent_depth = int(parent["depth"] or 0)
            if parent_depth >= MAX_QUESTION_DEPTH:
                raise ValueError("question nesting depth exceeds the configured limit")
            root_id = int(parent["root_question_id"] or parent["id"])
            question_depth = parent_depth + 1
        else:
            root_id = requested_root_id
            question_depth = requested_depth if requested_root_id else 0

        cursor = conn.execute(
            """
            INSERT INTO slide_questions (
                user_id, slide_id, question, quote_text, answer, model,
                root_question_id, parent_question_id, depth, quote_source, quote_source_question_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id_int,
                slide_id_int,
                question,
                quote_text,
                answer,
                model,
                root_id,
                parent_id,
                question_depth,
                clean_quote_source,
                quote_source_question,
            ),
        )
        question_id = int(cursor.lastrowid)
        if parent_id is None and root_id is None:
            conn.execute(
                """
                UPDATE slide_questions
                SET root_question_id = ?
                WHERE id = ?
                """,
                (question_id, question_id),
            )
        return question_id


def _optional_int(value: int | str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


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
            SELECT
                id,
                slide_id,
                question,
                quote_text,
                answer,
                model,
                category,
                status,
                sort_order,
                COALESCE(root_question_id, id) AS root_question_id,
                parent_question_id,
                COALESCE(depth, 0) AS depth,
                COALESCE(quote_source, 'slide') AS quote_source,
                quote_source_question_id,
                created_at
            FROM slide_questions
            WHERE user_id = ? AND slide_id IN ({placeholders})
            ORDER BY
                slide_id ASC,
                COALESCE(root_question_id, id) ASC,
                COALESCE(depth, 0) ASC,
                sort_order ASC,
                created_at ASC,
                id ASC
            """,
            (int(user_id), *tuple(chunk)),
        )
        for row in rows:
            grouped.setdefault(int(row["slide_id"]), []).append(row)
    return grouped


def flatten_question_subtree(user_id: int, question_id: int) -> int:
    user_id_int = int(user_id)
    question_id_int = int(question_id)
    with write_transaction() as conn:
        target = conn.execute(
            """
            SELECT id, root_question_id, depth
            FROM slide_questions
            WHERE user_id = ? AND id = ?
            """,
            (user_id_int, question_id_int),
        ).fetchone()
        if not target:
            return 0
        root_id = int(target["root_question_id"] or target["id"])
        next_depth = int(target["depth"] or 0) + 1

        rows = conn.execute(
            """
            WITH RECURSIVE descendants(id, parent_question_id, depth_order) AS (
                SELECT id, parent_question_id, 1
                FROM slide_questions
                WHERE user_id = ? AND parent_question_id = ?
                UNION ALL
                SELECT child.id, child.parent_question_id, descendants.depth_order + 1
                FROM slide_questions child
                JOIN descendants ON child.parent_question_id = descendants.id
                WHERE child.user_id = ?
            )
            SELECT id
            FROM descendants
            WHERE parent_question_id != ?
            ORDER BY depth_order ASC, id ASC
            """,
            (user_id_int, question_id_int, user_id_int, question_id_int),
        ).fetchall()
        if not rows:
            return 0

        max_row = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), 0) AS max_order
            FROM slide_questions
            WHERE user_id = ? AND parent_question_id = ?
            """,
            (user_id_int, question_id_int),
        ).fetchone()
        next_order = int(max_row["max_order"] or 0) if max_row else 0

        for row in rows:
            next_order += 1
            conn.execute(
                """
                UPDATE slide_questions
                SET parent_question_id = ?, root_question_id = ?, depth = ?, sort_order = ?
                WHERE id = ? AND user_id = ?
                """,
                (question_id_int, root_id, next_depth, next_order, int(row["id"]), user_id_int),
            )
        return len(rows)


def delete_slide_question_thread(user_id: int, question_id: int) -> int:
    user_id_int = int(user_id)
    question_id_int = int(question_id)
    with write_transaction() as conn:
        rows = conn.execute(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT id
                FROM slide_questions
                WHERE user_id = ? AND id = ?
                UNION ALL
                SELECT child.id
                FROM slide_questions child
                JOIN subtree ON child.parent_question_id = subtree.id
                WHERE child.user_id = ?
            )
            SELECT id
            FROM subtree
            ORDER BY id ASC
            """,
            (user_id_int, question_id_int, user_id_int),
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"""
            DELETE FROM slide_questions
            WHERE user_id = ? AND id IN ({placeholders})
            """,
            (user_id_int, *tuple(ids)),
        )
        return len(ids)


def update_slide_question_answer(user_id: int, question_id: int, answer: str) -> None:
    execute(
        """
        UPDATE slide_questions
        SET answer = ?
        WHERE user_id = ? AND id = ?
        """,
        (answer, int(user_id), int(question_id)),
    )
