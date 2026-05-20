from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from db import insert_and_get_id
from services.review_service import ensure_initial_review_tasks


def parse_study_assets(raw_text: str) -> dict[str, Any]:
    json_text = _extract_json_text(raw_text)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        payload = json.loads(_escape_latex_backslashes(json_text))
    if not isinstance(payload, dict):
        raise ValueError("API 返回内容不是 JSON 对象。")

    session = payload.get("study_session")
    cards = payload.get("knowledge_cards")
    if not isinstance(session, dict):
        raise ValueError("JSON 缺少 study_session 对象。")
    if not isinstance(cards, list):
        raise ValueError("JSON 缺少 knowledge_cards 数组。")

    normalized_cards = [card for card in cards if isinstance(card, dict)]
    if not normalized_cards:
        raise ValueError("knowledge_cards 为空，无法创建知识点卡片。")
    return {"study_session": session, "knowledge_cards": normalized_cards}


def save_study_assets(
    assets: dict[str, Any],
    *,
    fallback_subject: str,
    fallback_chapter: str,
) -> tuple[int, list[int]]:
    session = assets["study_session"]
    session_date = _text(session.get("date")) or date.today().isoformat()
    subject = _text(session.get("subject")) or fallback_subject or "未分类"
    chapter = _text(session.get("chapter")) or fallback_chapter
    mastery = _clamp_int(session.get("mastery"), 60)

    session_id = insert_and_get_id(
        """
        INSERT INTO study_sessions (
            date, subject, chapter, title, main_question, mastered_content,
            blockers, wrong_questions, summary, mastery, need_review, is_key
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_date,
            subject,
            chapter,
            _text(session.get("title")) or f"{chapter} 阅读复盘",
            _text(session.get("main_question")) or "这份资料主要想解决什么问题？",
            _text(session.get("mastered_content")),
            _text(session.get("blockers")),
            _text(session.get("wrong_questions")),
            _text(session.get("summary")),
            mastery,
            int(_bool(session.get("need_review"), True)),
            int(_bool(session.get("is_key"), mastery < 70)),
        ),
    )

    knowledge_ids: list[int] = []
    for card in assets["knowledge_cards"]:
        card_mastery = _clamp_int(card.get("mastery"), mastery)
        need_review = _bool(card.get("need_review"), True)
        knowledge_id = insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                subject, topic, core_question, one_sentence, logic_or_formula,
                application, mastery, need_review, source_session_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _text(card.get("subject")) or subject,
                _text(card.get("topic")) or "未命名知识点",
                _text(card.get("core_question")),
                _text(card.get("one_sentence")) or "待补充一句话解释",
                _text(card.get("logic_or_formula")),
                _text(card.get("application")),
                card_mastery,
                int(need_review),
                session_id,
            ),
        )
        if need_review:
            ensure_initial_review_tasks(knowledge_id, session_date)
        knowledge_ids.append(knowledge_id)

    return session_id, knowledge_ids


def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("API 返回内容里没有可解析的 JSON。")
    return text[start : end + 1]


def _escape_latex_backslashes(json_text: str) -> str:
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", json_text)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clamp_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, min(100, number))


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "需要", "是"}:
        return True
    if text in {"false", "0", "no", "n", "不需要", "否"}:
        return False
    return default
