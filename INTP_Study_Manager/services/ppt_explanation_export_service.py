from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path
import posixpath
from typing import Any

from db import DATA_DIR, fetch_all, fetch_one
from services.export_manifest_service import (
    PPT_EXPLANATION_SHARE_TYPE,
    PPT_EXPLANATION_SHARE_VERSION,
    PUBLIC_EXCLUDED_SECTIONS,
    PUBLIC_INCLUDED_SECTIONS,
    PUBLIC_PPT_PRIVACY_MODE,
    write_manifest,
)
from services.export_path_service import ensure_clean_dir, safe_filename, timestamp_slug, zip_directory
from services.export_privacy_service import assert_public_markdown_safe, assert_public_package_files_safe


def export_deck_share_package(user_id: int, deck_id: int, *, include_original: bool = False) -> dict[str, Any]:
    return _export_share_package(int(user_id), [int(deck_id)], include_original=include_original, legacy_single=True)


def export_decks_share_package(user_id: int, deck_ids: list[int], *, include_original: bool = False) -> dict[str, Any]:
    normalized_deck_ids = _normalize_deck_ids(deck_ids)
    if not normalized_deck_ids:
        raise ValueError("no decks selected")
    return _export_share_package(int(user_id), normalized_deck_ids, include_original=include_original, legacy_single=len(normalized_deck_ids) == 1)


def _export_share_package(user_id: int, deck_ids: list[int], *, include_original: bool, legacy_single: bool) -> dict[str, Any]:
    user_id_int = int(user_id)
    decks = _load_decks(user_id_int, deck_ids)
    slides_by_deck = _slides_by_deck(user_id_int, deck_ids)
    all_slides = [slide for deck_id in deck_ids for slide in slides_by_deck.get(int(deck_id), [])]
    latest = _latest_explanations_by_slide(user_id_int, [int(slide["id"]) for slide in all_slides])
    exported_at = datetime.now().isoformat(timespec="seconds")
    package_id = f"ppt-share-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
    root = DATA_DIR / "ppt_explanation_exports" / _package_dir_name(decks, timestamp_slug())
    ensure_clean_dir(root)

    flattened_slides: list[dict[str, Any]] = []
    deck_manifest: list[dict[str, Any]] = []
    for deck in decks:
        deck_id = int(deck["id"])
        deck_rel = "" if legacy_single else f"decks/deck-{deck_id}-{safe_filename(deck.get('title'), 'deck')}"
        _ensure_deck_dirs(root, deck_rel)
        slide_manifest: list[dict[str, Any]] = []
        slides = slides_by_deck.get(deck_id, [])
        for slide in slides:
            slide_number = int(slide["slide_number"])
            image_path = _copy_slide_image(slide, root, slide_number, relative_dir=_relative_dir(deck_rel, "images"))
            markdown_path = _relative_file(deck_rel, "slides", f"slide-{slide_number:03d}.md")
            explanation = latest.get(int(slide["id"]), {})
            slide_md = _slide_markdown(
                deck,
                slide,
                explanation,
                image_path=image_path,
                markdown_path=markdown_path,
                exported_at=exported_at,
                slide_count=len(slides),
            )
            assert_public_markdown_safe(slide_md)
            (root / markdown_path).write_text(slide_md, encoding="utf-8")
            item = {
                "deck_id": deck_id,
                "deck_title": deck.get("title") or "",
                "subject": deck.get("subject") or "",
                "slide_number": slide_number,
                "title": slide.get("title") or f"Slide {slide_number}",
                "markdown_path": markdown_path,
                "image_path": image_path,
            }
            slide_manifest.append(item)
            flattened_slides.append(item)

        original_path = _copy_original_file(deck, root, deck_rel, include_original=include_original)
        deck_entry = {
            "deck_id": deck_id,
            "subject": deck.get("subject") or "",
            "deck_title": deck.get("title") or "",
            "filename": deck.get("filename") or "",
            "slide_count": len(slides),
            "slides": slide_manifest,
        }
        if original_path:
            deck_entry["original_path"] = original_path
        deck_manifest.append(deck_entry)

    manifest = {
        "package_type": PPT_EXPLANATION_SHARE_TYPE,
        "version": PPT_EXPLANATION_SHARE_VERSION,
        "package_id": package_id,
        "subject": _package_subject(decks),
        "deck_title": _package_title(decks),
        "filename": decks[0].get("filename") or "" if len(decks) == 1 else "",
        "exported_at": exported_at,
        "deck_count": len(decks),
        "slide_count": len(flattened_slides),
        "privacy_mode": PUBLIC_PPT_PRIVACY_MODE,
        "included_sections": PUBLIC_INCLUDED_SECTIONS,
        "excluded_sections": PUBLIC_EXCLUDED_SECTIONS,
        "decks": deck_manifest,
        "slides": flattened_slides,
    }
    write_manifest(root / "manifest.json", manifest)
    (root / "README.md").write_text(_readme(deck_manifest, manifest), encoding="utf-8")
    (root / "_Deck_Home.md").write_text(_deck_home(deck_manifest, manifest), encoding="utf-8")
    assert_public_package_files_safe(root)
    zip_path = zip_directory(root, root.with_suffix(".zip"))
    return {
        "root": str(root),
        "zip_path": str(zip_path),
        "manifest": manifest,
        "deck_count": len(decks),
        "slide_count": len(flattened_slides),
    }


def _normalize_deck_ids(deck_ids: list[int]) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for deck_id in deck_ids:
        deck_id_int = int(deck_id)
        if deck_id_int in seen:
            continue
        seen.add(deck_id_int)
        normalized.append(deck_id_int)
    return normalized


def _load_decks(user_id: int, deck_ids: list[int]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in deck_ids)
    rows = fetch_all(
        f"SELECT * FROM ppt_decks WHERE user_id = ? AND id IN ({placeholders})",
        (int(user_id), *tuple(deck_ids)),
    )
    decks_by_id = {int(row["id"]): row for row in rows}
    missing = [deck_id for deck_id in deck_ids if deck_id not in decks_by_id]
    if missing:
        raise ValueError("deck not found")
    return [decks_by_id[deck_id] for deck_id in deck_ids]


def _slides_by_deck(user_id: int, deck_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    placeholders = ",".join("?" for _ in deck_ids)
    rows = fetch_all(
        f"""
        SELECT *
        FROM ppt_slides
        WHERE user_id = ? AND deck_id IN ({placeholders})
        ORDER BY deck_id ASC, slide_number ASC
        """,
        (int(user_id), *tuple(deck_ids)),
    )
    grouped = {int(deck_id): [] for deck_id in deck_ids}
    for row in rows:
        grouped.setdefault(int(row["deck_id"]), []).append(row)
    return grouped


def _package_dir_name(decks: list[dict[str, Any]], timestamp: str) -> str:
    if len(decks) == 1:
        deck = decks[0]
        return f"{safe_filename(deck.get('subject'), 'subject')}_{safe_filename(deck.get('title'), 'deck')}_{timestamp}"
    return f"{safe_filename(_package_subject(decks), 'subjects')}_{len(decks)}-decks_{timestamp}"


def _package_subject(decks: list[dict[str, Any]]) -> str:
    subjects = sorted({str(deck.get("subject") or "").strip() for deck in decks if str(deck.get("subject") or "").strip()})
    if len(subjects) == 1:
        return subjects[0]
    return "多科目" if subjects else ""


def _package_title(decks: list[dict[str, Any]]) -> str:
    if len(decks) == 1:
        return str(decks[0].get("title") or "")
    return f"{len(decks)} 个 PPT / PDF"


def _ensure_deck_dirs(root: Path, deck_rel: str) -> None:
    for dirname in ("slides", "images", "attachments"):
        (root / _relative_dir(deck_rel, dirname)).mkdir(parents=True, exist_ok=True)


def _relative_dir(deck_rel: str, dirname: str) -> str:
    return f"{deck_rel}/{dirname}" if deck_rel else dirname


def _relative_file(deck_rel: str, dirname: str, filename: str) -> str:
    return f"{_relative_dir(deck_rel, dirname)}/{filename}"


def _latest_explanations_by_slide(user_id: int, slide_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not slide_ids:
        return {}
    placeholders = ",".join("?" for _ in slide_ids)
    rows = fetch_all(
        f"""
        SELECT *
        FROM (
            SELECT se.*, ROW_NUMBER() OVER (PARTITION BY se.slide_id ORDER BY se.created_at DESC, se.id DESC) AS rn
            FROM slide_explanations se
            WHERE se.user_id = ? AND se.slide_id IN ({placeholders})
        )
        WHERE rn = 1
        """,
        (int(user_id), *tuple(slide_ids)),
    )
    return {int(row["slide_id"]): row for row in rows}


def _copy_slide_image(slide: dict, root: Path, slide_number: int, *, relative_dir: str = "images") -> str:
    source = Path(slide.get("image_path") or "")
    if not source.exists() or not source.is_file():
        return ""
    suffix = source.suffix.lower() or ".png"
    relative = f"{relative_dir}/slide-{slide_number:03d}{suffix}"
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, root / relative)
    return relative


def _copy_original_file(deck: dict, root: Path, deck_rel: str, *, include_original: bool) -> str:
    if not include_original:
        return ""
    source = Path(deck.get("file_path") or "")
    if not source.exists() or not source.is_file():
        return ""
    suffix = source.suffix.lower() or ".pptx"
    relative = _relative_file(deck_rel, "attachments", f"original{suffix}")
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, root / relative)
    return relative


def _slide_markdown(
    deck: dict,
    slide: dict,
    explanation: dict,
    *,
    image_path: str,
    markdown_path: str,
    exported_at: str,
    slide_count: int,
) -> str:
    slide_number = int(slide["slide_number"])
    title = slide.get("title") or f"Slide {slide_number}"
    image_section = f"![页面图片]({_image_link(markdown_path, image_path)})" if image_path else "没有导出页面图片。"
    facts = "\n".join(
        [
            f"- 科目：{deck.get('subject') or ''}",
            f"- PPT：{deck.get('title') or deck.get('filename') or ''}",
            f"- 页码：{slide_number}",
            f"- 标题：{title}",
            f"- 导出时间：{exported_at}",
        ]
    )
    return "\n\n".join(
        [
            "---",
            f"package_type: {PPT_EXPLANATION_SHARE_TYPE}",
            "type: slide_explanation",
            f"subject: {_yaml_text(deck.get('subject'))}",
            f"deck_title: {_yaml_text(deck.get('title'))}",
            f"slide_number: {slide_number}",
            f"title: {_yaml_text(title)}",
            f"exported_at: {exported_at}",
            f"privacy_mode: {PUBLIC_PPT_PRIVACY_MODE}",
            "---",
            f"# Slide {slide_number:03d}: {title}",
            facts,
            "## PPT/PDF 页面文字\n\n" + str(slide.get("slide_text") or ""),
            "## 页面图片\n\n" + image_section,
            "## AI 逐页讲解\n\n" + str(explanation.get("explanation") or ""),
            "## 自动摘要\n\n" + _summary(explanation.get("explanation") or slide.get("slide_text") or ""),
            "## 导航\n\n" + _navigation(slide_number, slide_count),
        ]
    )


def _image_link(markdown_path: str, image_path: str) -> str:
    start = posixpath.dirname(markdown_path) or "."
    return posixpath.relpath(image_path, start=start)


def _summary(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:180] + ("..." if len(text) > 180 else "")


def _navigation(slide_number: int, slide_count: int) -> str:
    prev_line = "上一页：无" if slide_number <= 1 else f"上一页：[[slide-{slide_number - 1:03d}]]"
    next_line = "下一页：无" if slide_number >= slide_count else f"下一页：[[slide-{slide_number + 1:03d}]]"
    return f"- {prev_line}\n- {next_line}"


def _readme(decks: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    deck_lines = "\n".join(
        f"- {deck.get('deck_title') or deck.get('filename') or '未命名'}：{deck.get('slide_count') or 0} 页"
        for deck in decks
    )
    return "\n\n".join(
        [
            f"# {manifest.get('deck_title') or 'PPT 讲解分享包'}",
            "这是公开分享包，只包含 PPT/PDF 页面文字、页面图片和 AI 逐页讲解。",
            f"- 科目：{manifest.get('subject') or ''}",
            f"- PPT/PDF 数量：{manifest.get('deck_count') or len(decks)}",
            f"- 页面数量：{manifest.get('slide_count') or 0}",
            "## 包含的 PPT/PDF",
            deck_lines,
        ]
    )


def _deck_home(decks: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    sections: list[str] = []
    for deck in decks:
        lines = "\n".join(
            f"- [Slide {int(slide['slide_number']):03d}: {slide.get('title') or ''}]({slide['markdown_path']})"
            for slide in deck.get("slides", [])
        )
        sections.append(
            "\n\n".join(
                [
                    f"## {deck.get('deck_title') or deck.get('filename') or '未命名 PPT/PDF'}",
                    f"- 科目：{deck.get('subject') or ''}",
                    f"- 页面数量：{deck.get('slide_count') or 0}",
                    lines,
                ]
            )
        )
    return "\n\n".join(
        [
            f"# {manifest.get('deck_title') or 'PPT 讲解分享包'}",
            f"- 科目：{manifest.get('subject') or ''}",
            f"- PPT/PDF 数量：{manifest.get('deck_count') or len(decks)}",
            f"- 页面数量：{manifest.get('slide_count') or 0}",
            *sections,
        ]
    )


def _yaml_text(value: object) -> str:
    return '"' + str(value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'
