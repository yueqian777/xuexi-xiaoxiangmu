from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path
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
    user_id_int = int(user_id)
    deck = fetch_one("SELECT * FROM ppt_decks WHERE user_id = ? AND id = ?", (user_id_int, int(deck_id)))
    if not deck:
        raise ValueError("deck not found")
    slides = fetch_all(
        "SELECT * FROM ppt_slides WHERE user_id = ? AND deck_id = ? ORDER BY slide_number ASC",
        (user_id_int, int(deck_id)),
    )
    latest = _latest_explanations_by_slide(user_id_int, [int(slide["id"]) for slide in slides])
    exported_at = datetime.now().isoformat(timespec="seconds")
    package_id = f"ppt-share-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
    root = DATA_DIR / "ppt_explanation_exports" / f"{safe_filename(deck.get('subject'), 'subject')}_{safe_filename(deck.get('title'), 'deck')}_{timestamp_slug()}"
    ensure_clean_dir(root)
    (root / "slides").mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "attachments").mkdir(parents=True, exist_ok=True)

    slide_manifest = []
    for slide in slides:
        slide_number = int(slide["slide_number"])
        image_path = _copy_slide_image(slide, root, slide_number)
        markdown_path = f"slides/slide-{slide_number:03d}.md"
        explanation = latest.get(int(slide["id"]), {})
        slide_md = _slide_markdown(deck, slide, explanation, image_path=image_path, exported_at=exported_at)
        assert_public_markdown_safe(slide_md)
        (root / markdown_path).write_text(slide_md, encoding="utf-8")
        slide_manifest.append(
            {
                "slide_number": slide_number,
                "title": slide.get("title") or f"Slide {slide_number}",
                "markdown_path": markdown_path,
                "image_path": image_path,
            }
        )

    if include_original:
        source = Path(deck.get("file_path") or "")
        if source.exists() and source.is_file():
            suffix = source.suffix.lower() or ".pptx"
            shutil.copy2(source, root / "attachments" / f"original{suffix}")

    manifest = {
        "package_type": PPT_EXPLANATION_SHARE_TYPE,
        "version": PPT_EXPLANATION_SHARE_VERSION,
        "package_id": package_id,
        "subject": deck.get("subject") or "",
        "deck_title": deck.get("title") or "",
        "filename": deck.get("filename") or "",
        "exported_at": exported_at,
        "slide_count": len(slides),
        "privacy_mode": PUBLIC_PPT_PRIVACY_MODE,
        "included_sections": PUBLIC_INCLUDED_SECTIONS,
        "excluded_sections": PUBLIC_EXCLUDED_SECTIONS,
        "slides": slide_manifest,
    }
    write_manifest(root / "manifest.json", manifest)
    (root / "README.md").write_text(_readme(deck), encoding="utf-8")
    (root / "_Deck_Home.md").write_text(_deck_home(deck, slide_manifest), encoding="utf-8")
    assert_public_package_files_safe(root)
    zip_path = zip_directory(root, root.with_suffix(".zip"))
    return {"root": str(root), "zip_path": str(zip_path), "manifest": manifest, "slide_count": len(slides)}


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


def _copy_slide_image(slide: dict, root: Path, slide_number: int) -> str:
    source = Path(slide.get("image_path") or "")
    if not source.exists() or not source.is_file():
        return ""
    suffix = source.suffix.lower() or ".png"
    relative = f"images/slide-{slide_number:03d}{suffix}"
    shutil.copy2(source, root / relative)
    return relative


def _slide_markdown(deck: dict, slide: dict, explanation: dict, *, image_path: str, exported_at: str) -> str:
    slide_number = int(slide["slide_number"])
    title = slide.get("title") or f"Slide {slide_number}"
    image_section = f"![Slide image](../{image_path})" if image_path else "No page image exported."
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
            "## Slide Content\n\n" + str(slide.get("slide_text") or ""),
            "## Page Image\n\n" + image_section,
            "## AI Explanation\n\n" + str(explanation.get("explanation") or ""),
            "## Summary\n\n" + _summary(explanation.get("explanation") or slide.get("slide_text") or ""),
            "## Previous / Next\n\n" + _navigation(slide_number),
        ]
    )


def _summary(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:180] + ("..." if len(text) > 180 else "")


def _navigation(slide_number: int) -> str:
    prev_line = "Previous: none" if slide_number <= 1 else f"Previous: [[slide-{slide_number - 1:03d}]]"
    return f"- {prev_line}\n- Next: [[slide-{slide_number + 1:03d}]]"


def _readme(deck: dict) -> str:
    return "\n\n".join(
        [
            f"# {deck.get('title') or 'PPT Explanation Share'}",
            "This public package only contains slide content and AI explanations.",
            "It excludes questions, knowledge cards, mistakes, review tasks, mastery, and personal learning records.",
        ]
    )


def _deck_home(deck: dict, slides: list[dict]) -> str:
    lines = "\n".join(f"- [[{Path(slide['markdown_path']).stem}]] {slide.get('title') or ''}" for slide in slides)
    return f"# {deck.get('title') or 'Deck'}\n\nSubject: {deck.get('subject') or ''}\n\n## Slides\n\n{lines}"


def _yaml_text(value: object) -> str:
    return '"' + str(value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'
