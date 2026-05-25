from __future__ import annotations

import json
import re
from typing import Any

from db import fetch_all, managed_connection

PAGE_TYPES = ("正文页", "公式页", "例题页", "过渡页", "目录页", "总结页")
LIGHTWEIGHT_PAGE_TYPES = {"过渡页", "目录页", "章节标题页", "标题页"}
CONTENT_PAGE_TYPES = {"正文页", "公式页", "例题页", "总结页"}


def format_pages_for_structure_prompt(slides: list[dict], *, per_page_limit: int = 420) -> str:
    chunks = []
    for slide in slides:
        text = _clip_text(slide.get("slide_text") or "", per_page_limit)
        chunks.append(
            "\n".join(
                [
                    f"第 {slide['slide_number']} 页",
                    f"标题：{slide.get('title') or '未命名页面'}",
                    f"识别文字：{text or '无可用文字'}",
                ]
            )
        )
    return "\n\n".join(chunks)


def parse_document_structure_response(text: str, slide_numbers: list[int]) -> dict[str, Any]:
    payload = _parse_json_payload(text)
    return normalize_document_structure(payload, slide_numbers)


def normalize_document_structure(payload: dict[str, Any], slide_numbers: list[int]) -> dict[str, Any]:
    slide_numbers = sorted({int(number) for number in slide_numbers if int(number) > 0})
    if not slide_numbers:
        return {"outline": "", "sections": [], "pages": []}

    first_slide = slide_numbers[0]
    last_slide = slide_numbers[-1]
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raw_sections = [
            {
                "section_index": 1,
                "title": "未分块内容",
                "topic": "",
                "core_question": "",
                "summary": str(payload.get("outline") or "").strip(),
                "key_terms": [],
                "prerequisite_concepts": [],
                "start_slide": first_slide,
                "end_slide": last_slide,
            }
        ]

    sections = _normalize_sections(raw_sections, first_slide, last_slide)
    raw_index_map = {
        _positive_int(raw.get("section_index"), position): section["section_index"]
        for position, (raw, section) in enumerate(zip(raw_sections, sections), start=1)
        if isinstance(raw, dict)
    }

    raw_pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    page_by_number: dict[int, dict[str, Any]] = {}
    for raw in raw_pages:
        if not isinstance(raw, dict):
            continue
        slide_number = _positive_int(raw.get("slide_number"), 0)
        if slide_number not in slide_numbers:
            continue
        raw_section_index = _positive_int(raw.get("section_index"), 0)
        section_index = raw_index_map.get(raw_section_index) or _section_index_for_slide(slide_number, sections)
        page_by_number[slide_number] = {
            "slide_number": slide_number,
            "section_index": section_index,
            "page_type": _normalize_optional_page_type(raw.get("page_type")),
            "one_sentence_summary": _text(raw.get("one_sentence_summary")),
            "slide_role": _text(raw.get("slide_role")),
            "key_points": _text(raw.get("key_points")),
        }

    pages = []
    for slide_number in slide_numbers:
        page = page_by_number.get(slide_number)
        if page is None:
            page = {
                "slide_number": slide_number,
                "section_index": _section_index_for_slide(slide_number, sections),
                "page_type": "",
                "one_sentence_summary": "",
                "slide_role": "",
                "key_points": "",
            }
        pages.append(page)

    return {
        "outline": _text(payload.get("outline")),
        "sections": sections,
        "pages": pages,
    }


def save_deck_structure(deck_id: int, structure: dict[str, Any]) -> None:
    deck_id = int(deck_id)
    sections = structure.get("sections") if isinstance(structure.get("sections"), list) else []
    pages = structure.get("pages") if isinstance(structure.get("pages"), list) else []
    with managed_connection() as conn:
        conn.execute("DELETE FROM ppt_sections WHERE deck_id = ?", (deck_id,))
        conn.execute(
            """
            UPDATE ppt_decks
            SET outline = ?, outline_generated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (_text(structure.get("outline")), deck_id),
        )
        conn.executemany(
            """
            INSERT INTO ppt_sections (
                deck_id, section_index, title, topic, core_question, summary,
                key_terms_json, prerequisite_concepts_json, start_slide, end_slide
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    deck_id,
                    int(section["section_index"]),
                    section["title"],
                    section.get("topic") or "",
                    section.get("core_question") or "",
                    section.get("summary") or "",
                    json.dumps(section.get("key_terms") or [], ensure_ascii=False),
                    json.dumps(section.get("prerequisite_concepts") or [], ensure_ascii=False),
                    int(section["start_slide"]),
                    int(section["end_slide"]),
                )
                for section in sections
            ),
        )
        conn.executemany(
            """
            UPDATE ppt_slides
            SET section_index = ?,
                page_type = ?,
                one_sentence_summary = ?,
                slide_role = ?,
                key_points = ?
            WHERE deck_id = ? AND slide_number = ?
            """,
            (
                (
                    int(page.get("section_index") or 0),
                    _normalize_optional_page_type(page.get("page_type")),
                    _text(page.get("one_sentence_summary")),
                    _text(page.get("slide_role")),
                    _text(page.get("key_points")),
                    deck_id,
                    int(page["slide_number"]),
                )
                for page in pages
            ),
        )


def fetch_deck_sections(deck_id: int) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT *
        FROM ppt_sections
        WHERE deck_id = ?
        ORDER BY section_index ASC
        """,
        (int(deck_id),),
    )
    sections = []
    for row in rows:
        row["key_terms"] = _json_list(row.get("key_terms_json"))
        row["prerequisite_concepts"] = _json_list(row.get("prerequisite_concepts_json"))
        sections.append(row)
    return sections


def build_slide_context_map(
    deck: dict,
    slides: list[dict],
    sections: list[dict],
) -> dict[int, dict[str, Any]]:
    section_by_index = {int(section["section_index"]): section for section in sections}
    slide_by_number = {int(slide["slide_number"]): slide for slide in slides}
    sorted_numbers = sorted(slide_by_number)
    contexts: dict[int, dict[str, Any]] = {}

    for position, slide_number in enumerate(sorted_numbers):
        slide = slide_by_number[slide_number]
        section = section_by_index.get(int(slide.get("section_index") or 0))
        if section is None and sections:
            section = next(
                (
                    item
                    for item in sections
                    if int(item["start_slide"]) <= slide_number <= int(item["end_slide"])
                ),
                sections[0],
            )
        section_index = int(section["section_index"]) if section else 0
        same_section = [
            item
            for item in slides
            if _section_index_for_slide(int(item["slide_number"]), sections) == section_index
            and int(item["slide_number"]) != slide_number
        ]
        related_pages = [
            _page_summary_line(item)
            for item in same_section
            if (item.get("one_sentence_summary") or item.get("title") or "").strip()
        ]
        prev_slide = slide_by_number.get(sorted_numbers[position - 1]) if position > 0 else None
        next_slide = slide_by_number.get(sorted_numbers[position + 1]) if position + 1 < len(sorted_numbers) else None
        contexts[slide_number] = {
            "deck_title": deck.get("title") or "学习资料",
            "subject": deck.get("subject") or "未分类",
            "section": section or {},
            "section_index": section_index,
            "slide": slide,
            "prev_slide": prev_slide,
            "next_slide": next_slide,
            "related_page_summaries": related_pages[:12],
            "formula_or_example_pages": [
                _page_summary_line(item)
                for item in same_section
                if item.get("page_type") in {"公式页", "例题页"}
            ][:8],
        }
    return contexts


def format_slide_context_package(context: dict[str, Any] | None) -> str:
    if not context:
        return "尚未生成文档级目录分块；请只依据当前页内容讲解。"
    section = context.get("section") or {}
    slide = context.get("slide") or {}
    prev_slide = context.get("prev_slide")
    next_slide = context.get("next_slide")
    lines = [
        f"资料：{context.get('deck_title') or '学习资料'}",
        f"当前目录块：{section.get('title') or '未分块'}，第 {section.get('start_slide') or '?'}-{section.get('end_slide') or '?'} 页",
        f"本块核心问题：{section.get('core_question') or '暂无'}",
        f"本块摘要：{section.get('summary') or '暂无'}",
        f"关键符号：{_join_list(section.get('key_terms'))}",
        f"前置概念：{_join_list(section.get('prerequisite_concepts'))}",
        "",
        f"当前页：第 {slide.get('slide_number')} 页，{slide.get('title') or '未命名页面'}",
        "",
        "邻近页线索：",
        f"- 上一页：{_page_summary_line(prev_slide) if prev_slide else '无'}",
        f"- 下一页：{_page_summary_line(next_slide) if next_slide else '无'}",
    ]
    related = context.get("related_page_summaries") or []
    if related:
        lines.extend(["", "当前目录块内相关页线索：", *[f"- {item}" for item in related]])
    formula_pages = context.get("formula_or_example_pages") or []
    if formula_pages:
        lines.extend(["", "同块内公式页 / 例题页线索：", *[f"- {item}" for item in formula_pages]])
    return "\n".join(lines).strip()


def should_use_lightweight_explanation(slide: dict) -> bool:
    page_type = str(slide.get("page_type") or "").strip()
    return page_type in LIGHTWEIGHT_PAGE_TYPES


def build_lightweight_explanation(deck: dict, slide: dict, context: dict[str, Any] | None) -> str:
    section = (context or {}).get("section") or {}
    related = (context or {}).get("related_page_summaries") or []
    page_type = slide.get("page_type") or "过渡页"
    slide_number = int(slide["slide_number"])
    title = slide.get("title") or "未命名页面"
    summary = slide.get("one_sentence_summary") or "本页主要承担结构过渡作用。"
    role = slide.get("slide_role") or "引出后续主题，不需要按正文页深讲。"
    next_core_pages = related[:5]
    lines = [
        f"## 第 {slide_number} 页：{title}",
        "",
        "### 本页定位",
        f"- 页面类型：{page_type}",
        f"- 一句话摘要：{summary}",
        f"- 作用：{role}",
        "",
        "### 当前目录块",
        f"- 标题：{section.get('title') or '未分块'}",
        f"- 页码范围：第 {section.get('start_slide') or slide_number}-{section.get('end_slide') or slide_number} 页",
        f"- 核心问题：{section.get('core_question') or '暂无'}",
        f"- 块摘要：{section.get('summary') or '暂无'}",
        "",
        "### 考点 / 学习抓手",
        f"- 关键符号：{_join_list(section.get('key_terms'))}",
        f"- 前置概念：{_join_list(section.get('prerequisite_concepts'))}",
    ]
    if slide.get("key_points"):
        lines.append(f"- 本页抓手：{slide['key_points']}")
    if next_core_pages:
        lines.extend(["", "### 后续核心页", *[f"- {item}" for item in next_core_pages]])
    lines.append("")
    lines.append("本页属于目录、章节入口或过渡页，不生成完整逐页讲解；请把注意力放到后续核心页。")
    return "\n".join(lines)


def _normalize_sections(raw_sections: list[Any], first_slide: int, last_slide: int) -> list[dict[str, Any]]:
    sections = []
    for position, raw in enumerate(raw_sections, start=1):
        if not isinstance(raw, dict):
            continue
        start_slide = _clamp_slide(_positive_int(raw.get("start_slide"), first_slide), first_slide, last_slide)
        end_slide = _clamp_slide(_positive_int(raw.get("end_slide"), start_slide), first_slide, last_slide)
        if start_slide > end_slide:
            start_slide, end_slide = end_slide, start_slide
        sections.append(
            {
                "section_index": len(sections) + 1,
                "title": _text(raw.get("title")) or f"第 {start_slide}-{end_slide} 页",
                "topic": _text(raw.get("topic")),
                "core_question": _text(raw.get("core_question")),
                "summary": _text(raw.get("summary")),
                "key_terms": _string_list(raw.get("key_terms")),
                "prerequisite_concepts": _string_list(raw.get("prerequisite_concepts")),
                "start_slide": start_slide,
                "end_slide": end_slide,
            }
        )

    if not sections:
        sections = [
            {
                "section_index": 1,
                "title": "未分块内容",
                "topic": "",
                "core_question": "",
                "summary": "",
                "key_terms": [],
                "prerequisite_concepts": [],
                "start_slide": first_slide,
                "end_slide": last_slide,
            }
        ]

    sections.sort(key=lambda item: (int(item["start_slide"]), int(item["end_slide"])))
    normalized = []
    cursor = first_slide
    for section in sections:
        start_slide = first_slide if not normalized else max(cursor, int(section["start_slide"]))
        end_slide = max(start_slide, int(section["end_slide"]))
        end_slide = min(end_slide, last_slide)
        if normalized and start_slide > cursor:
            normalized[-1]["end_slide"] = start_slide - 1
        section = {**section, "section_index": len(normalized) + 1, "start_slide": start_slide, "end_slide": end_slide}
        normalized.append(section)
        cursor = end_slide + 1
        if cursor > last_slide:
            break
    if normalized and normalized[-1]["end_slide"] < last_slide:
        normalized[-1]["end_slide"] = last_slide
    return normalized


def _parse_json_payload(text: str) -> dict[str, Any]:
    normalized = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", normalized, flags=re.S | re.I)
    if fenced:
        normalized = fenced.group(1).strip()
    if not normalized.startswith("{"):
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start >= 0 and end > start:
            normalized = normalized[start : end + 1]
    value = json.loads(normalized)
    if not isinstance(value, dict):
        raise ValueError("AI 分块结果必须是 JSON 对象。")
    return value


def _section_index_for_slide(slide_number: int, sections: list[dict[str, Any]]) -> int:
    for section in sections:
        if int(section["start_slide"]) <= slide_number <= int(section["end_slide"]):
            return int(section["section_index"])
    return int(sections[0]["section_index"]) if sections else 0


def _normalize_optional_page_type(value: Any) -> str:
    if not _text(value):
        return ""
    return _normalize_page_type(value)


def _normalize_page_type(value: Any) -> str:
    text = _text(value)
    if text in PAGE_TYPES:
        return text
    if text in LIGHTWEIGHT_PAGE_TYPES:
        return "目录页" if text == "目录页" else "过渡页"
    if "公式" in text:
        return "公式页"
    if "例" in text or "题" in text:
        return "例题页"
    if "目录" in text:
        return "目录页"
    if "总结" in text or "小结" in text:
        return "总结页"
    if "过渡" in text or "标题" in text or "章节" in text:
        return "过渡页"
    return "正文页"


def _page_summary_line(slide: dict | None) -> str:
    if not slide:
        return ""
    number = slide.get("slide_number")
    title = slide.get("title") or "未命名页面"
    page_type = slide.get("page_type") or "未标注"
    summary = slide.get("one_sentence_summary") or slide.get("slide_role") or "暂无摘要"
    return f"第 {number} 页（{page_type}）：{title}：{summary}"


def _clip_text(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _text(value: Any) -> str:
    return str(value or "").strip()


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _clamp_slide(value: int, first_slide: int, last_slide: int) -> int:
    return min(max(int(value), int(first_slide)), int(last_slide))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in re.split(r"[、,，;\n]+", value) if item.strip()]
    return []


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return _string_list(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return _string_list(value)
        return _string_list(parsed)
    return []


def _join_list(value: Any) -> str:
    items = _string_list(value)
    return "、".join(items) if items else "暂无"
