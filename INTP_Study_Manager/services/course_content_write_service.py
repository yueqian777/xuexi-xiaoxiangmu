from __future__ import annotations

from datetime import date
from typing import Any

from db import write_transaction
from services.course_service import ensure_course_for_subject
from services.review_service import ensure_initial_review_tasks


def create_study_session_record(
    user_id: int,
    *,
    session_date: str,
    subject: str,
    chapter: str,
    title: str,
    main_question: str,
    mastered_content: str,
    blockers: str,
    wrong_questions: str,
    summary: str,
    mastery: int,
    need_review: bool,
    is_key: bool,
    create_card: bool,
) -> tuple[int, int | None]:
    """Create one manual study record and its optional card atomically."""

    owner_id = int(user_id)
    clean_subject = _required_subject(subject)
    with write_transaction() as conn:
        course_id = ensure_course_for_subject(owner_id, clean_subject, conn=conn)
        cursor = conn.execute(
            """
            INSERT INTO study_sessions (
                user_id, date, subject, chapter, title, main_question, mastered_content,
                blockers, wrong_questions, summary, mastery, need_review, is_key, course_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id,
                str(session_date),
                clean_subject,
                _text(chapter),
                _text(title),
                _text(main_question),
                _text(mastered_content),
                _text(blockers),
                _text(wrong_questions),
                _text(summary),
                _mastery(mastery),
                int(bool(need_review)),
                int(bool(is_key)),
                course_id,
            ),
        )
        session_id = int(cursor.lastrowid)
        knowledge_id = None
        if create_card:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_cards (
                    user_id, subject, topic, core_question, one_sentence, logic_or_formula,
                    application, mastery, need_review, source_session_id, course_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_id,
                    clean_subject,
                    _text(title),
                    _text(main_question),
                    _text(mastered_content) or "待补充一句话解释",
                    _text(summary),
                    _text(wrong_questions),
                    _mastery(mastery),
                    int(bool(need_review)),
                    session_id,
                    course_id,
                ),
            )
            knowledge_id = int(cursor.lastrowid)
            if need_review:
                ensure_initial_review_tasks(
                    knowledge_id,
                    session_date,
                    user_id=owner_id,
                    conn=conn,
                )
    return session_id, knowledge_id


def update_study_session_record(
    user_id: int,
    session_id: int,
    *,
    session_date: str,
    subject: str,
    chapter: str,
    title: str,
    main_question: str,
    mastered_content: str,
    blockers: str,
    wrong_questions: str,
    summary: str,
    mastery: int,
    need_review: bool,
    is_key: bool,
) -> bool:
    owner_id = int(user_id)
    record_id = int(session_id)
    clean_subject = _required_subject(subject)
    with write_transaction() as conn:
        owned = conn.execute(
            "SELECT id FROM study_sessions WHERE user_id = ? AND id = ?",
            (owner_id, record_id),
        ).fetchone()
        if not owned:
            return False
        course_id = ensure_course_for_subject(owner_id, clean_subject, conn=conn)
        cursor = conn.execute(
            """
            UPDATE study_sessions
            SET date = ?, subject = ?, chapter = ?, title = ?, main_question = ?,
                mastered_content = ?, blockers = ?, wrong_questions = ?, summary = ?,
                mastery = ?, need_review = ?, is_key = ?, course_id = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                str(session_date),
                clean_subject,
                _text(chapter),
                _text(title),
                _text(main_question),
                _text(mastered_content),
                _text(blockers),
                _text(wrong_questions),
                _text(summary),
                _mastery(mastery),
                int(bool(need_review)),
                int(bool(is_key)),
                course_id,
                record_id,
                owner_id,
            ),
        )
        return int(cursor.rowcount or 0) == 1


def create_knowledge_card_record(
    user_id: int,
    *,
    subject: str,
    topic: str,
    core_question: str,
    one_sentence: str,
    logic_or_formula: str,
    application: str,
    mastery: int,
    need_review: bool,
    source_session_id: int | None = None,
    review_start_date: str | date | None = None,
) -> int:
    """Create a manual card, validating any inherited session course by owner."""

    owner_id = int(user_id)
    clean_subject = _required_subject(subject)
    with write_transaction() as conn:
        owned_source_session_id = None
        owned_course_id = None
        if source_session_id is not None:
            source = _owned_source_session(conn, owner_id, int(source_session_id))
            if source is None:
                raise ValueError("关联学习记录不存在。")
            owned_source_session_id = int(source["id"])
            owned_course_id = source.get("owned_course_id")
        course_id = owned_course_id or ensure_course_for_subject(
            owner_id,
            clean_subject,
            conn=conn,
        )
        cursor = conn.execute(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, core_question, one_sentence, logic_or_formula,
                application, mastery, need_review, source_session_id, course_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id,
                clean_subject,
                _text(topic),
                _text(core_question),
                _text(one_sentence),
                _text(logic_or_formula),
                _text(application),
                _mastery(mastery),
                int(bool(need_review)),
                owned_source_session_id,
                course_id,
            ),
        )
        knowledge_id = int(cursor.lastrowid)
        if need_review:
            ensure_initial_review_tasks(
                knowledge_id,
                review_start_date,
                user_id=owner_id,
                conn=conn,
            )
        return knowledge_id


def update_knowledge_card_record(
    user_id: int,
    knowledge_id: int,
    *,
    subject: str,
    topic: str,
    core_question: str,
    one_sentence: str,
    logic_or_formula: str,
    application: str,
    mastery: int,
    need_review: bool,
) -> bool:
    owner_id = int(user_id)
    card_id = int(knowledge_id)
    clean_subject = _required_subject(subject)
    with write_transaction() as conn:
        card_row = conn.execute(
            """
            SELECT
                kc.*,
                owned_card_course.id AS owned_card_course_id,
                source_session_course.id AS source_session_course_id,
                source_deck_course.id AS source_deck_course_id
            FROM knowledge_cards kc
            LEFT JOIN courses owned_card_course
              ON owned_card_course.id = kc.course_id
             AND owned_card_course.user_id = kc.user_id
            LEFT JOIN study_sessions source_session
              ON source_session.id = kc.source_session_id
             AND source_session.user_id = kc.user_id
            LEFT JOIN courses source_session_course
              ON source_session_course.id = source_session.course_id
             AND source_session_course.user_id = kc.user_id
            LEFT JOIN ppt_decks source_deck
              ON source_deck.id = kc.source_deck_id
             AND source_deck.user_id = kc.user_id
            LEFT JOIN courses source_deck_course
              ON source_deck_course.id = source_deck.course_id
             AND source_deck_course.user_id = kc.user_id
            WHERE kc.user_id = ? AND kc.id = ?
            """,
            (owner_id, card_id),
        ).fetchone()
        if not card_row:
            return False
        card = dict(card_row)
        has_source = bool(card.get("source_deck_id") or card.get("source_session_id"))
        if has_source:
            course_id = (
                card.get("source_deck_course_id")
                or card.get("source_session_course_id")
                or card.get("owned_card_course_id")
            )
        else:
            course_id = None
        if not course_id:
            course_id = ensure_course_for_subject(owner_id, clean_subject, conn=conn)
        cursor = conn.execute(
            """
            UPDATE knowledge_cards
            SET subject = ?, topic = ?, core_question = ?, one_sentence = ?,
                logic_or_formula = ?, application = ?, mastery = ?, need_review = ?, course_id = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                clean_subject,
                _text(topic),
                _text(core_question),
                _text(one_sentence),
                _text(logic_or_formula),
                _text(application),
                _mastery(mastery),
                int(bool(need_review)),
                course_id,
                card_id,
                owner_id,
            ),
        )
        if need_review:
            ensure_initial_review_tasks(
                card_id,
                card.get("created_at"),
                user_id=owner_id,
                conn=conn,
            )
        return int(cursor.rowcount or 0) == 1


def convert_parking_question_to_card(
    user_id: int,
    parking_id: int,
    *,
    topic: str,
    one_sentence: str,
    logic_or_formula: str,
    application: str,
    mastery: int,
    need_review: bool,
) -> int | None:
    """Convert a parking item once; BEGIN IMMEDIATE serializes duplicate submits."""

    owner_id = int(user_id)
    item_id = int(parking_id)
    with write_transaction() as conn:
        parking_row = conn.execute(
            "SELECT * FROM parking_lot WHERE user_id = ? AND id = ?",
            (owner_id, item_id),
        ).fetchone()
        if not parking_row:
            return None
        parking = dict(parking_row)
        if parking.get("status") == "已转知识点":
            return None
        subject = _text(parking.get("subject")) or "未分类"
        course_id = ensure_course_for_subject(owner_id, subject, conn=conn)
        cursor = conn.execute(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, core_question, one_sentence, logic_or_formula,
                application, mastery, need_review, course_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id,
                subject,
                _text(topic),
                _text(parking.get("question")),
                _text(one_sentence),
                _text(logic_or_formula),
                _text(application),
                _mastery(mastery),
                int(bool(need_review)),
                course_id,
            ),
        )
        knowledge_id = int(cursor.lastrowid)
        if need_review:
            ensure_initial_review_tasks(
                knowledge_id,
                user_id=owner_id,
                conn=conn,
            )
        updated = conn.execute(
            """
            UPDATE parking_lot
            SET status = '已转知识点'
            WHERE id = ? AND user_id = ? AND status <> '已转知识点'
            """,
            (item_id, owner_id),
        )
        if int(updated.rowcount or 0) != 1:
            raise RuntimeError("停车场问题状态更新失败。")
        return knowledge_id


def _owned_source_session(conn, user_id: int, session_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT s.id, c.id AS owned_course_id
        FROM study_sessions s
        LEFT JOIN courses c
          ON c.id = s.course_id
         AND c.user_id = s.user_id
        WHERE s.user_id = ? AND s.id = ?
        """,
        (user_id, session_id),
    ).fetchone()
    return dict(row) if row else None


def _required_subject(value: object) -> str:
    subject = _text(value)
    if not subject:
        raise ValueError("科目不能为空。")
    return subject


def _text(value: object) -> str:
    return str(value or "").strip()


def _mastery(value: object) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))
