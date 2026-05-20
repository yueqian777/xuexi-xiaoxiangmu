from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Mapping

BASE_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = BASE_DIR / "prompts"


@lru_cache(maxsize=32)
def load_template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def render_template(name: str, replacements: Mapping[str, str]) -> str:
    text = load_template(name)
    for key, value in replacements.items():
        text = text.replace("{" + key + "}", value)
    return text


def format_study_record(record: Mapping) -> str:
    return "\n".join(
        [
            f"日期：{record.get('date', '')}",
            f"科目：{record.get('subject', '')}",
            f"章节 / 课程：{record.get('chapter', '')}",
            f"主题：{record.get('title', '')}",
            f"核心问题：{record.get('main_question', '')}",
            f"已掌握内容：{record.get('mastered_content', '')}",
            f"卡点：{record.get('blockers', '')}",
            f"错题或不会的问题：{record.get('wrong_questions', '')}",
            f"总结：{record.get('summary', '')}",
            f"掌握度：{record.get('mastery', 0)}",
        ]
    )


def format_knowledge_card(card: Mapping) -> str:
    return "\n".join(
        [
            f"科目：{card.get('subject', '')}",
            f"知识点：{card.get('topic', '')}",
            f"核心问题：{card.get('core_question', '')}",
            f"一句话解释：{card.get('one_sentence', '')}",
            f"公式 / 逻辑推导：{card.get('logic_or_formula', '')}",
            f"典型题 / 应用场景：{card.get('application', '')}",
            f"掌握度：{card.get('mastery', 0)}",
        ]
    )
