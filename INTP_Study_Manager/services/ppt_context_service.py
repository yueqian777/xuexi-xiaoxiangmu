from __future__ import annotations

import json
import re
from typing import Any

from db import fetch_all, write_transaction

PAGE_TYPES = ("讲解页", "正文页", "公式页", "例题页", "过渡页", "目录页", "总结页")
LIGHTWEIGHT_PAGE_TYPES = {"过渡页", "目录页", "章节标题页", "标题页"}
CONTENT_PAGE_TYPES = {"讲解页", "正文页", "公式页", "例题页", "总结页"}


def detailed_explanation_profile() -> dict[str, Any]:
    """Return the shared, transport-neutral contract for a high-detail page explanation."""

    return {
        "profile_id": "detailed_page_tutor_v2",
        "intent": "以目录块为骨架，把当前页讲成可独立复习、又能接回整章主线的学习材料。",
        "target_length": {
            "content_page_chars": [900, 1500],
            "transition_page_chars": [250, 450],
        },
        "required_blocks": [
            "章节定位与本页任务",
            "核心概念与物理图像",
            "公式与推导逐步拆解",
            "前后页连接",
            "易错点与适用条件",
            "闭卷自测",
        ],
        "formula_rules": [
            "逐一定义公式中的关键符号、方向、单位或量纲以及成立条件。",
            "按从已知到结论的顺序补出页面省略的中间逻辑，但不得编造课件之外的结论。",
            "区分数学形式、物理意义和实际使用步骤；有方向约定时必须明确说明。",
        ],
        "quality_rules": [
            "先说明本页位于哪个目录块、承接什么、为下一页准备什么。",
            "不要复述 OCR；优先解释为什么、如何推导、何时使用以及和相邻概念的区别。",
            "OCR、图示或公式无法可靠辨认时要明确标注不确定处，不得自行补造。",
            "过渡页保持简洁；正文、公式和例题页必须达到可脱离幻灯片复习的完整度。",
            "每页保留独立标题和页面标签，批量生成时不得把多页压缩成一段总摘要。",
        ],
    }


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


def parse_document_structure_response(text: str, slides: list[int] | list[dict]) -> dict[str, Any]:
    payload = _parse_json_payload(text)
    return normalize_document_structure(payload, slides)


def normalize_document_structure(payload: dict[str, Any], slides: list[int] | list[dict]) -> dict[str, Any]:
    slide_meta = _slide_metadata_map(slides)
    slide_numbers = sorted(slide_meta)
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

    raw_pages = []
    for key in ("pages", "transition_pages"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_pages.extend(value)
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
            inferred = _infer_page_metadata(slide_meta.get(slide_number, {}), sections)
            page = {
                "slide_number": slide_number,
                "section_index": _section_index_for_slide(slide_number, sections),
                "page_type": inferred.get("page_type", ""),
                "one_sentence_summary": inferred.get("one_sentence_summary", ""),
                "slide_role": inferred.get("slide_role", ""),
                "key_points": inferred.get("key_points", ""),
            }
        pages.append(page)

    return {
        "outline": _text(payload.get("outline")),
        "sections": sections,
        "pages": pages,
    }


def infer_document_structure_from_titles(slides: list[dict]) -> dict[str, Any]:
    """Infer a conservative local outline without calling an AI provider.

    Many teaching decks repeat the course title on each subsection divider. Those
    repeated, well-spaced pages are strong structural signals. When the signal is
    absent this returns one continuous block instead of inventing fixed-size chapters.
    """

    slide_meta = _slide_metadata_map(slides)
    ordered = [slide_meta[number] for number in sorted(slide_meta)]
    if not ordered:
        return {"outline": "", "sections": [], "pages": []}

    title_occurrences: dict[str, list[int]] = {}
    for slide in ordered:
        key = _normalized_title_key(slide.get("title"))
        if key:
            title_occurrences.setdefault(key, []).append(int(slide["slide_number"]))

    repeated_transition_keys = {
        key
        for key, numbers in title_occurrences.items()
        if _is_repeated_transition_group(numbers, len(ordered))
    }
    first_slide = int(ordered[0]["slide_number"])
    boundary_numbers = {first_slide}
    transition_numbers: set[int] = set()
    for slide in ordered:
        number = int(slide["slide_number"])
        title_key = _normalized_title_key(slide.get("title"))
        combined = f"{_text(slide.get('title'))}\n{_text(slide.get('slide_text'))}".strip()
        repeated_divider = title_key in repeated_transition_keys
        explicit_divider = (
            len(re.sub(r"\s+", "", combined)) <= 220
            and _looks_like_transition_title(_text(slide.get("title")))
            and (number == first_slide or title_key not in {"引言", "绪论"})
        )
        if repeated_divider or explicit_divider:
            boundary_numbers.add(number)
            transition_numbers.add(number)

    max_reasonable_boundaries = min(12, max(2, (len(ordered) + 1) // 2))
    if len(boundary_numbers) > max_reasonable_boundaries:
        boundary_numbers = {first_slide}
        transition_numbers.clear()

    starts = sorted(boundary_numbers)
    last_slide = int(ordered[-1]["slide_number"])
    sections: list[dict[str, Any]] = []
    for position, start_slide in enumerate(starts):
        end_slide = starts[position + 1] - 1 if position + 1 < len(starts) else last_slide
        block = [
            slide
            for slide in ordered
            if start_slide <= int(slide["slide_number"]) <= end_slide
        ]
        title = _infer_local_section_title(
            block,
            repeated_transition_keys=repeated_transition_keys,
        )
        section_index = len(sections) + 1
        sections.append(
            {
                "section_index": section_index,
                "title": title,
                "topic": title,
                "core_question": f"如何理解并串联“{title}”中的核心定义、公式与物理意义？",
                "summary": _local_section_summary(block, repeated_transition_keys),
                "key_terms": _local_section_key_terms(block, repeated_transition_keys),
                "prerequisite_concepts": [],
                "start_slide": start_slide,
                "end_slide": end_slide,
            }
        )

    if len(sections) == 1 and first_slide not in transition_numbers:
        transition_numbers.clear()

    transition_pages = []
    for slide_number in sorted(transition_numbers):
        section = next(
            item
            for item in sections
            if int(item["start_slide"]) <= slide_number <= int(item["end_slide"])
        )
        next_start = min(slide_number + 1, int(section["end_slide"]))
        transition_pages.append(
            {
                "slide_number": slide_number,
                "section_index": int(section["section_index"]),
                "page_type": "过渡页",
                "one_sentence_summary": f"进入“{section['title']}”目录块。",
                "slide_role": "章节入口，建立本块问题主线。",
                "key_points": (
                    f"先明确本块核心问题，再阅读第 {next_start}-{section['end_slide']} 页。"
                    if next_start < int(section["end_slide"])
                    else "先明确本块核心问题，再进入正文。"
                ),
            }
        )

    outline = "；".join(
        f"{section['section_index']}. {section['title']}（第 {section['start_slide']}-{section['end_slide']} 页）"
        for section in sections
    )
    return normalize_document_structure(
        {
            "outline": outline,
            "sections": sections,
            "transition_pages": transition_pages,
        },
        ordered,
    )


def save_deck_structure(
    deck_id: int,
    structure: dict[str, Any],
    *,
    user_id: int | None = None,
    conn: Any | None = None,
) -> None:
    deck_id = int(deck_id)
    expected_user_id = int(user_id) if user_id is not None else None
    sections = structure.get("sections") if isinstance(structure.get("sections"), list) else []
    pages = structure.get("pages") if isinstance(structure.get("pages"), list) else []
    if conn is not None:
        _save_deck_structure_with_connection(
            conn,
            deck_id,
            expected_user_id,
            structure,
            sections,
            pages,
        )
        return
    with write_transaction() as write_conn:
        _save_deck_structure_with_connection(
            write_conn,
            deck_id,
            expected_user_id,
            structure,
            sections,
            pages,
        )


def _save_deck_structure_with_connection(
    conn: Any,
    deck_id: int,
    expected_user_id: int | None,
    structure: dict[str, Any],
    sections: list[dict[str, Any]],
    pages: list[dict[str, Any]],
) -> None:
    if expected_user_id is None:
        deck = conn.execute("SELECT id, user_id FROM ppt_decks WHERE id = ?", (deck_id,)).fetchone()
    else:
        deck = conn.execute(
            "SELECT id, user_id FROM ppt_decks WHERE id = ? AND user_id = ?",
            (deck_id, expected_user_id),
        ).fetchone()
    if not deck:
        raise PermissionError("无权更新这份 PPT 资料。") if expected_user_id is not None else ValueError("PPT 资料不存在。")
    owner_id = int(deck["user_id"])

    conn.execute("DELETE FROM ppt_sections WHERE deck_id = ? AND user_id = ?", (deck_id, owner_id))
    conn.execute(
        """
        UPDATE ppt_decks
        SET outline = ?, outline_generated_at = datetime('now', 'localtime')
        WHERE id = ? AND user_id = ?
        """,
        (_text(structure.get("outline")), deck_id, owner_id),
    )
    conn.executemany(
        """
        INSERT INTO ppt_sections (
            user_id, deck_id, section_index, title, topic, core_question, summary,
            key_terms_json, prerequisite_concepts_json, start_slide, end_slide
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                owner_id,
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
        WHERE user_id = ? AND deck_id = ? AND slide_number = ?
        """,
        (
            (
                int(page.get("section_index") or 0),
                _normalize_optional_page_type(page.get("page_type")),
                _text(page.get("one_sentence_summary")),
                _text(page.get("slide_role")),
                _text(page.get("key_points")),
                owner_id,
                deck_id,
                int(page["slide_number"]),
            )
            for page in pages
        ),
    )


def fetch_deck_sections(deck_id: int, *, user_id: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...]
    user_clause = ""
    if user_id is not None:
        user_clause = "AND user_id = ?"
        params = (int(deck_id), int(user_id))
    else:
        params = (int(deck_id),)
    rows = fetch_all(
        f"""
        SELECT *
        FROM ppt_sections
        WHERE deck_id = ?
        {user_clause}
        ORDER BY section_index ASC
        """,
        params,
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
    resolved_section_by_slide = {
        slide_number: _section_index_for_slide(slide_number, sections)
        for slide_number in sorted_numbers
    }
    slides_by_section: dict[int, list[dict]] = {}
    for slide_number in sorted_numbers:
        slides_by_section.setdefault(resolved_section_by_slide[slide_number], []).append(slide_by_number[slide_number])
    summary_lines_by_section: dict[int, list[tuple[int, str]]] = {}
    formula_lines_by_section: dict[int, list[tuple[int, str]]] = {}
    formula_page_types = {"公式页", "例题页"}
    for section_index, section_slides in slides_by_section.items():
        summary_lines: list[tuple[int, str]] = []
        formula_lines: list[tuple[int, str]] = []
        for item in section_slides:
            item_number = int(item["slide_number"])
            if (item.get("one_sentence_summary") or item.get("title") or "").strip():
                summary_lines.append((item_number, _page_summary_line(item)))
            if item.get("page_type") in formula_page_types:
                formula_lines.append((item_number, _page_summary_line(item)))
        summary_lines_by_section[section_index] = summary_lines
        formula_lines_by_section[section_index] = formula_lines
    contexts: dict[int, dict[str, Any]] = {}

    for position, slide_number in enumerate(sorted_numbers):
        slide = slide_by_number[slide_number]
        section = section_by_index.get(int(slide.get("section_index") or 0))
        if section is None and sections:
            section = section_by_index.get(resolved_section_by_slide[slide_number], sections[0])
        section_index = int(section["section_index"]) if section else 0
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
            "related_page_summaries": _limited_context_lines(
                summary_lines_by_section.get(section_index, []),
                slide_number,
                12,
            ),
            "formula_or_example_pages": _limited_context_lines(
                formula_lines_by_section.get(section_index, []),
                slide_number,
                8,
            ),
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
        f"当前页标签：{slide.get('page_type') or '未标注'}",
        f"当前页作用：{slide.get('slide_role') or '暂无'}",
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


def _limited_context_lines(items: list[tuple[int, str]], current_slide_number: int, limit: int) -> list[str]:
    return [line for slide_number, line in items if slide_number != current_slide_number][:limit]


def should_use_lightweight_explanation(slide: dict) -> bool:
    # Older imported structures may persist labels such as "章节页" or
    # "章节标题页". Normalize before deciding so legacy transition pages do
    # not get sent through the full content-page generation path. The
    # normalizer checks content labels (for example "章节正文页") first, so a
    # real正文页 remains a content page.
    page_type = _normalize_page_type(slide.get("page_type"))
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
    display_title = section.get("title") or title
    metadata = {
        "title": _clip_text(str(display_title or title), 80),
        "page_type": _normalize_page_type(page_type),
    }
    return "\n".join(
        [
            f"<!-- INTP_SLIDE_META {json.dumps(metadata, ensure_ascii=False)} -->",
            f"## [[第 {slide_number} 页]] [[标签:{metadata['page_type']}]]：{metadata['title']}",
            "",
            *lines[2:],
        ]
    )


def extract_generated_slide_metadata(explanation: str, *, slide_number: int, fallback_title: str = "") -> dict[str, str]:
    source = str(explanation or "")
    metadata = _metadata_from_json_comment(source)
    title = _text(metadata.get("title")) if metadata else ""
    page_type = _normalize_optional_page_type(metadata.get("page_type")) if metadata else ""

    if not title:
        heading = re.search(r"^\s*#{1,3}\s*(.+?)\s*$", source, flags=re.M)
        if heading:
            title = _clean_generated_title(heading.group(1), slide_number)
    if not title:
        title = _text(fallback_title) or f"第 {slide_number} 页"
    if not page_type:
        page_type = _infer_generated_page_type(source)

    return {
        "title": _clip_text(title, 80),
        "page_type": page_type or "讲解页",
    }


def _metadata_from_json_comment(source: str) -> dict[str, Any]:
    match = re.search(r"<!--\s*INTP_SLIDE_META\s*(\{.*?\})\s*-->", source, flags=re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _clean_generated_title(value: str, slide_number: int) -> str:
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", str(value or ""))
    text = re.sub(r"第\s*\d+\s*页", "", text)
    text = re.sub(r"(讲解页|正文页|公式页|例题页|总结页|过渡页|目录页)", "", text)
    text = re.sub(r"^[：:·\-\s]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:·-")
    return text or f"第 {slide_number} 页"


def _infer_generated_page_type(source: str) -> str:
    text = str(source or "")
    if "例题" in text or "题解" in text or "解法" in text:
        return "例题页"
    if "$" in text or "\\(" in text or "\\[" in text or "公式" in text or "推导" in text:
        return "公式页"
    if "总结" in text or "小结" in text or "复盘" in text:
        return "总结页"
    return "讲解页"


def _slide_metadata_map(slides: list[int] | list[dict]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in slides:
        if isinstance(item, dict):
            number = _positive_int(item.get("slide_number"), 0)
            if number > 0:
                result[number] = item
        else:
            number = _positive_int(item, 0)
            if number > 0:
                result[number] = {"slide_number": number}
    return result


def _infer_page_metadata(slide: dict[str, Any], sections: list[dict[str, Any]]) -> dict[str, str]:
    slide_number = _positive_int(slide.get("slide_number"), 0)
    text = _text(slide.get("slide_text"))
    title = _text(slide.get("title"))
    combined = f"{title}\n{text}".strip()
    normalized = re.sub(r"\s+", "", combined).lower()
    line_count = len([line for line in re.split(r"[\r\n]+", combined) if line.strip()])
    char_count = len(normalized)
    section_start = any(int(section["start_slide"]) == slide_number for section in sections)

    if char_count <= 140 and ("目录" in normalized or "contents" in normalized):
        return {
            "page_type": "目录页",
            "one_sentence_summary": "本页是目录或章节导航页。",
            "slide_role": "提示后续内容结构，不展开逐页知识讲解。",
            "key_points": "关注后续目录块的核心页。",
        }
    if char_count <= 120 and line_count <= 4 and section_start and _looks_like_transition_title(combined):
        return {
            "page_type": "过渡页",
            "one_sentence_summary": "本页是目录块入口或章节标题页。",
            "slide_role": "引出当前目录块主题，不承载独立知识点。",
            "key_points": "把注意力转到本块后续核心页。",
        }
    return {}


def _looks_like_transition_title(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "")).lower()
    patterns = (
        r"^第[一二三四五六七八九十\d]+[章节篇部分]",
        r"chapter\d*",
        r"section\d*",
        r"^模块\d*",
        r"^专题",
        r"^绪论$",
        r"^引言$",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _normalized_title_key(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", _text(value).lower())


def _is_repeated_transition_group(numbers: list[int], slide_count: int) -> bool:
    if len(numbers) < 3:
        return False
    if len(numbers) > max(3, int(slide_count * 0.45)):
        return False
    gaps = [right - left for left, right in zip(numbers, numbers[1:])]
    if not gaps:
        return False
    return sum(gap >= 2 for gap in gaps) >= max(1, len(gaps) - 1) and max(gaps) >= 3


def _infer_local_section_title(
    block: list[dict[str, Any]],
    *,
    repeated_transition_keys: set[str],
) -> str:
    if not block:
        return "未分块内容"
    heading = _extract_section_heading(block[0])
    if heading:
        return heading
    for slide in block:
        title = _text(slide.get("title"))
        if title and _normalized_title_key(title) not in repeated_transition_keys:
            return _clip_text(title, 48)
    first_number = int(block[0]["slide_number"])
    last_number = int(block[-1]["slide_number"])
    return f"第 {first_number}-{last_number} 页"


def _extract_section_heading(slide: dict[str, Any]) -> str:
    candidates = [
        line.strip(" ：:·-")
        for line in re.split(r"[\r\n]+", _text(slide.get("slide_text")))
        if line.strip()
    ]
    patterns = (
        r"^第[一二三四五六七八九十百\d]+章\s*.{1,48}$",
        r"^\d+(?:\.\d+)+\s*.{1,48}$",
    )
    for line in candidates:
        normalized = re.sub(r"\s+", " ", line).strip()
        if len(normalized) <= 64 and any(re.match(pattern, normalized) for pattern in patterns):
            return normalized
    title = re.sub(r"\s+", " ", _text(slide.get("title"))).strip()
    if title and _looks_like_transition_title(title):
        return _clip_text(title, 48)
    return ""


def _local_section_summary(block: list[dict[str, Any]], repeated_keys: set[str]) -> str:
    titles = _distinct_local_titles(block, repeated_keys, limit=4)
    if titles:
        return "本块依次覆盖：" + "、".join(titles) + "。"
    start = int(block[0]["slide_number"])
    end = int(block[-1]["slide_number"])
    return f"本块覆盖第 {start}-{end} 页，按页面顺序建立知识主线。"


def _local_section_key_terms(block: list[dict[str, Any]], repeated_keys: set[str]) -> list[str]:
    return [_clip_text(title, 30) for title in _distinct_local_titles(block, repeated_keys, limit=6)]


def _distinct_local_titles(
    block: list[dict[str, Any]],
    repeated_keys: set[str],
    *,
    limit: int,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for slide in block:
        title = re.sub(r"\s+", " ", _text(slide.get("title"))).strip()
        key = _normalized_title_key(title)
        if not title or key in repeated_keys or key in seen:
            continue
        seen.add(key)
        result.append(_clip_text(title, 48))
        if len(result) >= limit:
            break
    return result


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
    if "讲解" in text or "正文" in text or "概念" in text:
        return "讲解页"
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
