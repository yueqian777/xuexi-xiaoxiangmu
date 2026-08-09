from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import db
from repositories.ppt_repository import latest_explanations_by_slide_ids
from services import chatgpt_explanation_schema as schema
from services.export_manifest_service import write_manifest
from services.export_path_service import ensure_clean_dir, safe_filename, zip_directory


RANGE_MODES = frozenset({"section", "custom", "all"})


def bridge_directories(
    user_id: int | None = None,
    task_id: str | None = None,
) -> dict[str, Path]:
    """Return deterministic bridge paths without relying on Streamlit state."""

    tasks_root = db.DATA_DIR / "chatgpt_tasks"
    result: dict[str, Path] = {
        "tasks": tasks_root,
        "tasks_root": tasks_root,
        "inbox": db.DATA_DIR / "chatgpt_inbox",
        "imported": db.DATA_DIR / "chatgpt_imported",
    }
    if user_id is not None:
        user_root = tasks_root / f"user_{int(user_id)}"
        result["user_tasks"] = user_root
        if task_id is not None:
            clean_task_id = _normalize_task_id(task_id)
            task_root = user_root / clean_task_id
            result.update(
                {
                    "task": task_root,
                    "package": task_root / "package",
                    "zip": task_root / f"chatgpt_task_{clean_task_id}.zip",
                }
            )
    elif task_id is not None:
        raise ValueError("重建任务路径时必须提供 user_id")
    return result


def task_package_path(user_id: int, task_id: str) -> Path:
    return bridge_directories(user_id, task_id)["zip"]


def task_package_directory(user_id: int, task_id: str) -> Path:
    return bridge_directories(user_id, task_id)["package"]


def parse_slide_number_spec(value: str | Iterable[int]) -> list[int]:
    """Parse ``1-3, 5`` or normalize an iterable into sorted unique pages."""

    if isinstance(value, str):
        text = value.strip().replace("，", ",")
        if not text:
            raise ValueError("请输入页码")
        numbers: set[int] = set()
        for raw_part in text.split(","):
            part = raw_part.strip()
            if not part:
                raise ValueError("页码格式不正确")
            if "-" in part:
                pieces = [piece.strip() for piece in part.split("-")]
                if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
                    raise ValueError(f"页码范围格式不正确：{part}")
                start, end = (int(piece) for piece in pieces)
                if start <= 0 or end <= 0 or start > end:
                    raise ValueError(f"页码范围不正确：{part}")
                numbers.update(range(start, end + 1))
            else:
                if not part.isdigit() or int(part) <= 0:
                    raise ValueError(f"页码格式不正确：{part}")
                numbers.add(int(part))
        return sorted(numbers)

    try:
        numbers = {int(item) for item in value}
    except (TypeError, ValueError) as exc:
        raise ValueError("页码必须是正整数") from exc
    if not numbers or any(number <= 0 for number in numbers):
        raise ValueError("页码必须是正整数")
    return sorted(numbers)


def compute_deck_fingerprint(
    deck: Mapping[str, Any],
    slides: Sequence[Mapping[str, Any]],
) -> str:
    """Hash stable deck content; paths, filenames and mtimes are excluded."""

    deck_item = dict(deck)
    ordered_slides = sorted(
        (dict(slide) for slide in slides),
        key=lambda item: (
            _as_int(item.get("slide_number")),
            _as_int(item.get("id") if item.get("id") is not None else item.get("slide_id")),
        ),
    )
    canonical = {
        "deck_id": _as_int(
            deck_item.get("id") if deck_item.get("id") is not None else deck_item.get("deck_id")
        ),
        "deck_title": _as_text(deck_item.get("title")),
        "subject": _as_text(deck_item.get("subject")),
        "slide_count": len(ordered_slides),
        "slides": [
            {
                "slide_id": _as_int(
                    slide.get("id") if slide.get("id") is not None else slide.get("slide_id")
                ),
                "slide_number": _as_int(slide.get("slide_number")),
                "title": _as_text(slide.get("title")),
                "slide_text": _as_text(slide.get("slide_text")),
            }
            for slide in ordered_slides
        ],
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def deck_fingerprint(user_id: int, deck_id: int) -> str:
    deck, slides, _ = _load_deck_context(int(user_id), int(deck_id))
    return compute_deck_fingerprint(deck, slides)


def plan_task_packages(
    user_id: int,
    deck_id: int,
    *,
    range_mode: str,
    section_index: int | None = None,
    slide_numbers: str | Iterable[int] | None = None,
    max_slides_per_task: int = schema.DEFAULT_MAX_SLIDES_PER_TASK,
) -> dict[str, Any]:
    """Plan section/custom/all packages without writing files or database rows."""

    user_id_int = int(user_id)
    deck_id_int = int(deck_id)
    clean_mode = str(range_mode or "").strip().lower()
    if clean_mode not in RANGE_MODES:
        raise ValueError("不支持的任务页码范围")
    max_slides = _validate_max_slides(max_slides_per_task)
    deck, slides, sections = _load_deck_context(user_id_int, deck_id_int)
    if not slides:
        raise ValueError("该 PPT 没有可讲解页面")

    if clean_mode == "section":
        if section_index is None:
            raise ValueError("请选择当前目录块")
        chunks = _plan_section_chunks(slides, sections, int(section_index), max_slides)
    elif clean_mode == "custom":
        if slide_numbers is None:
            raise ValueError("请输入自定义页码")
        requested_numbers = parse_slide_number_spec(slide_numbers)
        selected = _select_slides_by_number(slides, requested_numbers)
        chunks = _fixed_chunks(selected, max_slides, sections)
    else:
        chunks = _plan_all_chunks(slides, sections, max_slides)

    fingerprint = compute_deck_fingerprint(deck, slides)
    requested_slide_count = sum(len(chunk["slides"]) for chunk in chunks)
    return {
        "user_id": user_id_int,
        "deck_id": deck_id_int,
        "deck": deck,
        "deck_title": _as_text(deck.get("title")),
        "subject": _as_text(deck.get("subject")),
        "deck_fingerprint": fingerprint,
        "range_mode": clean_mode,
        "requested_slide_count": requested_slide_count,
        "slide_count": requested_slide_count,
        "package_count": len(chunks),
        "chunks": chunks,
    }


def create_task_packages(
    user_id: int,
    deck_id: int,
    *,
    range_mode: str,
    section_index: int | None = None,
    slide_numbers: str | Iterable[int] | None = None,
    include_images: bool = False,
    include_existing_explanations: bool = False,
    max_slides_per_task: int = schema.DEFAULT_MAX_SLIDES_PER_TASK,
) -> dict[str, Any]:
    """Create ZIP task packages and persist one waiting task per ZIP."""

    plan = plan_task_packages(
        user_id,
        deck_id,
        range_mode=range_mode,
        section_index=section_index,
        slide_numbers=slide_numbers,
        max_slides_per_task=max_slides_per_task,
    )
    user_id_int = int(user_id)
    deck_id_int = int(deck_id)
    all_slide_ids = [
        int(slide["id"])
        for chunk in plan["chunks"]
        for slide in chunk["slides"]
    ]
    existing_by_slide = (
        latest_explanations_by_slide_ids(user_id_int, all_slide_ids)
        if include_existing_explanations
        else {}
    )

    packages: list[dict[str, Any]] = []
    for chunk in plan["chunks"]:
        package = _create_one_package(
            user_id_int,
            deck_id_int,
            plan,
            chunk,
            include_images=bool(include_images),
            include_existing_explanations=bool(include_existing_explanations),
            existing_by_slide=existing_by_slide,
        )
        packages.append(package)

    return {
        "user_id": user_id_int,
        "deck_id": deck_id_int,
        "deck_title": plan["deck_title"],
        "subject": plan["subject"],
        "range_mode": plan["range_mode"],
        "requested_slide_count": plan["requested_slide_count"],
        "slide_count": plan["requested_slide_count"],
        "package_count": len(packages),
        "packages": packages,
    }


def list_tasks(
    user_id: int,
    statuses: str | Iterable[str] | None = None,
    *,
    parse_json: bool = True,
) -> list[dict[str, Any]]:
    """List only the current user's tasks, newest first."""

    db.init_db()
    params: list[Any] = [int(user_id)]
    where = "user_id = ?"
    normalized_statuses = _normalize_statuses(statuses)
    if normalized_statuses is not None:
        if not normalized_statuses:
            return []
        placeholders = ",".join("?" for _ in normalized_statuses)
        where += f" AND status IN ({placeholders})"
        params.extend(normalized_statuses)
    rows = db.fetch_all(
        f"""
        SELECT *
        FROM chatgpt_explanation_tasks
        WHERE {where}
        ORDER BY created_at DESC, id DESC
        """,
        params,
    )
    return [_task_record(row, parse_json=parse_json) for row in rows]


def get_task(
    user_id: int,
    task_id: str,
    *,
    parse_json: bool = True,
) -> dict[str, Any] | None:
    db.init_db()
    row = db.fetch_one(
        """
        SELECT *
        FROM chatgpt_explanation_tasks
        WHERE user_id = ? AND task_id = ?
        """,
        (int(user_id), str(task_id or "").strip()),
    )
    return _task_record(row, parse_json=parse_json) if row else None


def _create_one_package(
    user_id: int,
    deck_id: int,
    plan: Mapping[str, Any],
    chunk: Mapping[str, Any],
    *,
    include_images: bool,
    include_existing_explanations: bool,
    existing_by_slide: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    task_id = _new_task_id()
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    paths = bridge_directories(user_id, task_id)
    task_root = paths["task"]
    package_root = paths["package"]
    ensure_clean_dir(task_root)
    package_root.mkdir(parents=True, exist_ok=True)

    requested_slides = [
        {"slide_id": int(slide["id"]), "slide_number": int(slide["slide_number"])}
        for slide in chunk["slides"]
    ]
    manifest = {
        "package_type": schema.TASK_PACKAGE_TYPE,
        "version": schema.TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "user_id": int(user_id),
        "deck_id": int(deck_id),
        "deck_fingerprint": plan["deck_fingerprint"],
        "subject": plan["subject"],
        "deck_title": plan["deck_title"],
        "created_at": created_at,
        "requested_slide_count": len(requested_slides),
        "requested_slides": requested_slides,
        "result_schema_version": schema.RESULT_SCHEMA_VERSION,
        "privacy_mode": schema.PRIVACY_MODE,
    }
    if set(manifest) != set(schema.TASK_MANIFEST_ALLOWLIST):
        raise ValueError("任务 manifest 字段不符合隐私白名单")

    slide_payloads = _build_slide_payloads(
        chunk["slides"],
        chunk.get("sections") or [],
        package_root,
        include_images=include_images,
        include_existing_explanations=include_existing_explanations,
        existing_by_slide=existing_by_slide,
    )
    slides_payload = {
        "task_id": task_id,
        "deck_id": int(deck_id),
        "deck_fingerprint": plan["deck_fingerprint"],
        "subject": plan["subject"],
        "deck_title": plan["deck_title"],
        "sections": list(chunk.get("sections") or []),
        "slides": slide_payloads,
    }

    write_manifest(package_root / "manifest.json", manifest)
    write_manifest(package_root / "slides.json", slides_payload)
    (package_root / "instructions.md").write_text(
        _instructions(manifest),
        encoding="utf-8",
    )
    _assert_task_package_files(package_root)
    zip_path = zip_directory(package_root, paths["zip"])

    db.insert_and_get_id(
        """
        INSERT INTO chatgpt_explanation_tasks (
            user_id, task_id, deck_id, deck_fingerprint, requested_slides_json,
            package_path, status, manifest_json
        )
        VALUES (?, ?, ?, ?, ?, ?, 'waiting_result', ?)
        """,
        (
            int(user_id),
            task_id,
            int(deck_id),
            plan["deck_fingerprint"],
            _json_dump(requested_slides),
            str(zip_path),
            _json_dump(manifest),
        ),
    )
    return {
        "task_id": task_id,
        "root": str(package_root),
        "zip_path": str(zip_path),
        "slide_count": len(requested_slides),
        "requested_slides": requested_slides,
        "manifest": manifest,
        "slides": slide_payloads,
        "status": "waiting_result",
    }


def _build_slide_payloads(
    slides: Sequence[Mapping[str, Any]],
    sections: Sequence[Mapping[str, Any]],
    package_root: Path,
    *,
    include_images: bool,
    include_existing_explanations: bool,
    existing_by_slide: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    section_by_index = {
        int(section["section_index"]): section
        for section in sections
        if section.get("section_index") is not None
    }
    payloads: list[dict[str, Any]] = []
    total_image_bytes = 0
    for slide in slides:
        slide_id = int(slide["id"])
        slide_number = int(slide["slide_number"])
        section = section_by_index.get(int(slide.get("section_index") or 0), {})
        payload: dict[str, Any] = {
            "slide_id": slide_id,
            "slide_number": slide_number,
            "title": _as_text(slide.get("title")),
            "slide_text": _as_text(slide.get("slide_text")),
            "section_index": int(slide.get("section_index") or 0),
            "section_title": _as_text(section.get("title")),
            "section_summary": _as_text(section.get("summary")),
            "page_type": _as_text(slide.get("page_type")),
            "slide_role": _as_text(slide.get("slide_role")),
            "key_points": _as_text(slide.get("key_points")),
        }
        if include_images:
            image_path, image_bytes = _copy_task_image(slide, package_root, slide_number)
            total_image_bytes += image_bytes
            if total_image_bytes > schema.MAX_TOTAL_IMAGE_BYTES:
                raise ValueError("任务包图片总大小超过限制")
            if image_path:
                payload["image_path"] = image_path
        if include_existing_explanations:
            explanation = existing_by_slide.get(slide_id)
            if explanation:
                payload["existing_explanation"] = _as_text(explanation.get("explanation"))
        unexpected = set(payload).difference(schema.SLIDE_PAYLOAD_ALLOWLIST)
        if unexpected:
            raise ValueError(f"页面字段不符合隐私白名单：{sorted(unexpected)}")
        payloads.append(payload)
    return payloads


def _copy_task_image(
    slide: Mapping[str, Any],
    package_root: Path,
    slide_number: int,
) -> tuple[str, int]:
    raw_path = _as_text(slide.get("image_path"))
    if not raw_path:
        return "", 0
    source = Path(raw_path)
    if not source.exists() or not source.is_file():
        return "", 0
    source = source.resolve()
    try:
        source.relative_to(db.DATA_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"第 {slide_number} 页图片路径不安全") from exc
    suffix = source.suffix.lower()
    if suffix not in schema.SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"第 {slide_number} 页图片格式不受支持")
    size = source.stat().st_size
    if size > schema.MAX_IMAGE_BYTES:
        raise ValueError(f"第 {slide_number} 页图片过大")
    relative = Path("images") / f"slide-{slide_number:03d}{suffix}"
    destination = package_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return relative.as_posix(), size


def _instructions(manifest: Mapping[str, Any]) -> str:
    requested = list(manifest["requested_slides"])
    first = requested[0]
    example = {
        "package_type": schema.RESULT_PACKAGE_TYPE,
        "version": schema.RESULT_SCHEMA_VERSION,
        "result_id": "result-20260809-0123456789ab",
        "task_id": manifest["task_id"],
        "deck_id": manifest["deck_id"],
        "deck_fingerprint": manifest["deck_fingerprint"],
        "generator": schema.CHATGPT_WEB_GENERATOR,
        "generated_at": "2026-08-09T12:00:00+08:00",
        "slides": [
            {
                "slide_id": first["slide_id"],
                "slide_number": first["slide_number"],
                "explanation": "Markdown 讲解",
            }
        ],
    }
    example_json = json.dumps(example, ensure_ascii=False, indent=2)
    return f"""# INTP Study Manager：ChatGPT 网页逐页讲解任务

请先阅读 `manifest.json` 与完整的 `slides.json`，理解本任务中的目录结构、页面顺序和前后页关系，再逐页生成讲解。不要只复述幻灯片原文。

每页讲解应尽量说明：

1. 这一页解决什么问题；
2. 核心概念，以及公式、推导或逻辑；
3. 为什么这样处理；
4. 它与前后页的关系；
5. 容易混淆或误用的地方。

正文使用 Markdown，数学公式尽量使用 LaTeX。不得修改或自行补造 `task_id`、`deck_id`、`deck_fingerprint`、`slide_id`、`slide_number`，也不得添加任务中不存在的页面。必须覆盖 `manifest.json` 的 `requested_slides`；如果确实无法完成某页，就不要伪造内容。

最终必须生成一个可下载的 `{schema.RESULT_FILENAME}` 文件，严格使用 UTF-8 JSON 和以下结构。不要只把最终结果打印在聊天正文中。

```json
{example_json}
```

结果文件的 `slides` 中每一项只对应一张请求页面。示例中的 `result_id` 与 `generated_at` 必须替换为本次生成的唯一标识和实际 ISO 8601 时间；每次重新生成都使用新的 `result_id`，以便保留多个讲解版本。
"""


def _assert_task_package_files(root: Path) -> None:
    allowed_root_files = {"manifest.json", "instructions.md", "slides.json"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if len(relative.parts) == 1 and relative.name in allowed_root_files:
            continue
        if (
            len(relative.parts) == 2
            and relative.parts[0] == "images"
            and relative.suffix.lower() in schema.SUPPORTED_IMAGE_EXTENSIONS
        ):
            continue
        raise ValueError(f"任务包包含未允许的文件：{relative.as_posix()}")


def _load_deck_context(
    user_id: int,
    deck_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    db.init_db()
    deck = db.fetch_one(
        """
        SELECT id, user_id, title, subject, slide_count
        FROM ppt_decks
        WHERE id = ? AND user_id = ?
        """,
        (int(deck_id), int(user_id)),
    )
    if not deck:
        raise ValueError("PPT 不存在或不属于当前用户")
    slides = db.fetch_all(
        """
        SELECT id, user_id, deck_id, slide_number, title, slide_text, image_path,
               section_index, page_type, one_sentence_summary, slide_role, key_points
        FROM ppt_slides
        WHERE deck_id = ? AND user_id = ?
        ORDER BY slide_number ASC, id ASC
        """,
        (int(deck_id), int(user_id)),
    )
    sections_raw = db.fetch_all(
        """
        SELECT section_index, title, topic, core_question, summary,
               key_terms_json, prerequisite_concepts_json, start_slide, end_slide
        FROM ppt_sections
        WHERE deck_id = ? AND user_id = ?
        ORDER BY section_index ASC, id ASC
        """,
        (int(deck_id), int(user_id)),
    )
    sections = [_section_payload(section) for section in sections_raw]
    return deck, slides, sections


def _section_payload(section: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "section_index": int(section.get("section_index") or 0),
        "title": _as_text(section.get("title")),
        "topic": _as_text(section.get("topic")),
        "core_question": _as_text(section.get("core_question")),
        "summary": _as_text(section.get("summary")),
        "key_terms": _json_string_list(section.get("key_terms_json")),
        "prerequisite_concepts": _json_string_list(section.get("prerequisite_concepts_json")),
        "start_slide": int(section.get("start_slide") or 0),
        "end_slide": int(section.get("end_slide") or 0),
    }
    if set(payload).difference(schema.SECTION_PAYLOAD_ALLOWLIST):
        raise ValueError("目录块字段不符合隐私白名单")
    return payload


def _plan_section_chunks(
    slides: Sequence[Mapping[str, Any]],
    sections: Sequence[Mapping[str, Any]],
    section_index: int,
    max_slides: int,
) -> list[dict[str, Any]]:
    section = next(
        (item for item in sections if int(item["section_index"]) == int(section_index)),
        None,
    )
    if section:
        selected = [
            slide
            for slide in slides
            if int(section["start_slide"]) <= int(slide["slide_number"]) <= int(section["end_slide"])
        ]
    else:
        selected = [
            slide for slide in slides if int(slide.get("section_index") or 0) == int(section_index)
        ]
        if selected:
            section = {
                "section_index": int(section_index),
                "title": f"目录块 {int(section_index)}",
                "topic": "",
                "core_question": "",
                "summary": "",
                "key_terms": [],
                "prerequisite_concepts": [],
                "start_slide": int(selected[0]["slide_number"]),
                "end_slide": int(selected[-1]["slide_number"]),
            }
    if not section or not selected:
        raise ValueError("当前目录块没有可讲解页面")
    return _chunks(selected, max_slides, [section])


def _plan_all_chunks(
    slides: Sequence[Mapping[str, Any]],
    sections: Sequence[Mapping[str, Any]],
    max_slides: int,
) -> list[dict[str, Any]]:
    if not sections:
        return _fixed_chunks(slides, max_slides, sections)
    chunks: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    for section in sections:
        section_slides = [
            slide
            for slide in slides
            if int(slide["id"]) not in used_ids
            and int(section["start_slide"])
            <= int(slide["slide_number"])
            <= int(section["end_slide"])
        ]
        if not section_slides:
            continue
        used_ids.update(int(slide["id"]) for slide in section_slides)
        chunks.extend(_chunks(section_slides, max_slides, [section]))
    unassigned = [slide for slide in slides if int(slide["id"]) not in used_ids]
    for run in _contiguous_slide_runs(unassigned):
        chunks.extend(_fixed_chunks(run, max_slides, sections))
    chunks.sort(key=lambda chunk: (int(chunk["start_slide"]), int(chunk["end_slide"])))
    return chunks


def _fixed_chunks(
    slides: Sequence[Mapping[str, Any]],
    max_slides: int,
    sections: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for start in range(0, len(slides), max_slides):
        group = list(slides[start : start + max_slides])
        if not group:
            continue
        result.extend(_chunks(group, max_slides, _sections_for_slides(group, sections)))
    return result


def _chunks(
    slides: Sequence[Mapping[str, Any]],
    max_slides: int,
    sections: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for start in range(0, len(slides), max_slides):
        group = [dict(slide) for slide in slides[start : start + max_slides]]
        if not group:
            continue
        first_number = int(group[0]["slide_number"])
        last_number = int(group[-1]["slide_number"])
        result.append(
            {
                "label": f"第 {first_number}-{last_number} 页",
                "start_slide": first_number,
                "end_slide": last_number,
                "slide_count": len(group),
                "sections": [dict(section) for section in sections],
                "slides": group,
            }
        )
    return result


def _sections_for_slides(
    slides: Sequence[Mapping[str, Any]],
    sections: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    numbers = {int(slide["slide_number"]) for slide in slides}
    return [
        dict(section)
        for section in sections
        if any(int(section["start_slide"]) <= number <= int(section["end_slide"]) for number in numbers)
    ]


def _contiguous_slide_runs(
    slides: Sequence[Mapping[str, Any]],
) -> list[list[Mapping[str, Any]]]:
    runs: list[list[Mapping[str, Any]]] = []
    for slide in slides:
        if not runs or int(slide["slide_number"]) != int(runs[-1][-1]["slide_number"]) + 1:
            runs.append([slide])
        else:
            runs[-1].append(slide)
    return runs


def _select_slides_by_number(
    slides: Sequence[Mapping[str, Any]],
    requested_numbers: Sequence[int],
) -> list[dict[str, Any]]:
    by_number = {int(slide["slide_number"]): dict(slide) for slide in slides}
    missing = [number for number in requested_numbers if number not in by_number]
    if missing:
        rendered = ", ".join(str(number) for number in missing)
        raise ValueError(f"页码不存在：{rendered}")
    return [by_number[number] for number in requested_numbers]


def _validate_max_slides(value: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("每个任务包的页数必须是整数") from exc
    if normalized <= 0 or normalized > schema.MAX_SLIDES_PER_TASK:
        raise ValueError(f"每个任务包页数必须在 1-{schema.MAX_SLIDES_PER_TASK} 之间")
    return normalized


def _normalize_statuses(statuses: str | Iterable[str] | None) -> list[str] | None:
    if statuses is None:
        return None
    raw_statuses = [statuses] if isinstance(statuses, str) else list(statuses)
    normalized: list[str] = []
    seen: set[str] = set()
    for status in raw_statuses:
        clean = str(status or "").strip()
        if not clean:
            continue
        if clean not in schema.TASK_STATUSES:
            raise ValueError(f"不支持的任务状态：{clean}")
        if clean not in seen:
            normalized.append(clean)
            seen.add(clean)
    return normalized


def _task_record(row: Mapping[str, Any], *, parse_json: bool) -> dict[str, Any]:
    item = dict(row)
    rebuilt_path = task_package_path(int(item["user_id"]), str(item["task_id"]))
    stored_value = str(item.get("package_path") or "").strip()
    stored_path = Path(stored_value) if stored_value else rebuilt_path
    package_path = rebuilt_path if rebuilt_path.is_file() else stored_path
    item["package_path"] = str(package_path)
    item["zip_path"] = str(package_path)
    if parse_json:
        item["requested_slides"] = _stored_json(item.get("requested_slides_json"), [])
        item["manifest"] = _stored_json(item.get("manifest_json"), {})
    return item


def _stored_json(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _json_string_list(value: Any) -> list[str]:
    parsed = _stored_json(value, [])
    return [_as_text(item) for item in parsed if _as_text(item)]


def _normalize_task_id(task_id: str) -> str:
    raw = str(task_id or "").strip()
    if not raw:
        raise ValueError("task_id 不能为空")
    clean = safe_filename(raw, "task", max_length=120)
    if clean != raw:
        raise ValueError("task_id 包含不安全字符")
    return clean


def _new_task_id() -> str:
    return f"task-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:12]}"


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_text(value: Any) -> str:
    return str(value or "")
