from __future__ import annotations

from typing import Any, Mapping

from services.mastery_service import clamp_mastery


def mastery_level(value: Any) -> dict[str, str | int]:
    score = clamp_mastery(_safe_int(value, 0))
    if score >= 85:
        return {
            "score": score,
            "label": "迁移熟练",
            "hint": "优先做变式题和跨章节迁移。",
        }
    if score >= 70:
        return {
            "score": score,
            "label": "基本掌握",
            "hint": "用闭卷解释和典型题保持稳定。",
        }
    if score >= 45:
        return {
            "score": score,
            "label": "巩固中",
            "hint": "先补公式条件、推导断点和易混点。",
        }
    return {
        "score": score,
        "label": "薄弱",
        "hint": "今天优先复习，先重新回答核心问题。",
    }


def knowledge_card_preview_markdown(card: Mapping[str, Any]) -> str:
    level = mastery_level(card.get("mastery", 0))
    subject = _text(card.get("subject")) or "未分类"
    topic = _text(card.get("topic")) or "未命名知识点"
    core_question = _text(card.get("core_question")) or "待补充核心问题"
    one_sentence = _text(card.get("one_sentence")) or "待补充一句话解释"
    logic_or_formula = _text(card.get("logic_or_formula")) or "待补充公式、推导或因果链"
    application = _text(card.get("application")) or "待补充典型题、应用场景或识别信号"

    return "\n\n".join(
        [
            f"### {topic}",
            f"`{subject}` · 掌握度 **{level['score']}%** · **{level['label']}**",
            f"**核心问题**\n\n{core_question}",
            f"**一句话抓手**\n\n{one_sentence}",
            f"**公式 / 推导**\n\n{logic_or_formula}",
            f"**应用 / 快速定位**\n\n{application}",
            f"**下一步**\n\n{level['hint']}",
        ]
    )


def compact_card_index_rows(cards: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        level = mastery_level(card.get("mastery", 0))
        rows.append(
            {
                "id": int(card.get("id") or 0),
                "科目": _text(card.get("subject")),
                "知识点": _text(card.get("topic")),
                "核心问题": _clip(_text(card.get("core_question")), 72),
                "掌握度": int(level["score"]),
                "状态": str(level["label"]),
                "需要复习": "是" if bool(card.get("need_review")) else "否",
                "创建时间": _text(card.get("created_at")),
            }
        )
    return rows


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
