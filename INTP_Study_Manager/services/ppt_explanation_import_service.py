from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from db import DATA_DIR, fetch_one, write_transaction
from services.export_manifest_service import read_manifest, validate_public_ppt_manifest
from services.export_path_service import safe_extract_zip, safe_filename

SLIDE_TEXT_STOP_HEADINGS = [
    "页面图片",
    "Page Image",
    "Slide Image",
    "Slide Images",
    "AI Explanation",
    "AI 逐页讲解",
    "自动摘要",
    "Auto Summary",
    "Summary",
    "导航",
    "Navigation",
]
EXPLANATION_STOP_HEADINGS = [
    "自动摘要",
    "Auto Summary",
    "Summary",
    "导航",
    "Navigation",
]


def preview_share_package(user_id: int, zip_file: Any) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        source = _materialize_zip(zip_file, Path(tmp) / "package.zip")
        extract_dir = Path(tmp) / "extract"
        safe_extract_zip(source, extract_dir)
        manifest = _load_and_validate_manifest(extract_dir)
        decks = _manifest_decks(manifest)
        duplicate = _existing_package(int(user_id), manifest["package_id"]) is not None
        return {
            "package_id": manifest["package_id"],
            "package_type": manifest["package_type"],
            "version": manifest.get("version", ""),
            "privacy_mode": manifest["privacy_mode"],
            "subject": manifest.get("subject", ""),
            "deck_title": _preview_deck_title(manifest, decks),
            "deck_count": len(decks),
            "slide_count": sum(int(deck.get("slide_count") or len(deck["slides"])) for deck in decks),
            "has_original": _package_has_original(extract_dir),
            "already_imported": duplicate,
            "manifest": manifest,
        }


def import_share_package(user_id: int, zip_file: Any, *, duplicate_policy: str = "copy") -> dict[str, Any]:
    user_id_int = int(user_id)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        source = _materialize_zip(zip_file, Path(tmp) / "package.zip")
        extract_dir = Path(tmp) / "extract"
        safe_extract_zip(source, extract_dir)
        manifest = _load_and_validate_manifest(extract_dir)
        decks = _manifest_decks(manifest)
        if _existing_package(user_id_int, manifest["package_id"]) and duplicate_policy == "skip":
            return {
                "status": "skipped",
                "package_id": manifest["package_id"],
                "deck_id": None,
                "deck_ids": [],
                "deck_count": len(decks),
            }

        asset_key = manifest["package_id"]
        if _existing_package(user_id_int, manifest["package_id"]):
            asset_key = f"{asset_key}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        asset_root = DATA_DIR / "imported_assets" / f"user_{user_id_int}" / safe_filename(asset_key, "package")
        if asset_root.exists():
            shutil.rmtree(asset_root)
        asset_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extract_dir / "manifest.json", asset_root / "manifest.json")
        (asset_root / "images").mkdir(parents=True, exist_ok=True)

        with write_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO import_packages (
                    user_id, package_id, package_type, package_version, privacy_mode,
                    subject, title, source_filename, manifest_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id_int,
                    manifest["package_id"],
                    manifest["package_type"],
                    manifest.get("version", ""),
                    manifest["privacy_mode"],
                    manifest.get("subject", ""),
                    _preview_deck_title(manifest, decks),
                    Path(str(getattr(zip_file, "name", "share.zip"))).name,
                    json.dumps(manifest, ensure_ascii=False),
                ),
            )
            import_package_id = int(cursor.lastrowid)
            deck_ids = []
            for deck_index, deck in enumerate(decks, start=1):
                deck_cursor = conn.execute(
                    """
                    INSERT INTO ppt_decks (
                        user_id, filename, title, subject, file_path, slide_count,
                        import_package_id, source_type, source_package_id, imported_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'ppt_explanation_share', ?, ?)
                    """,
                    (
                        user_id_int,
                        deck.get("filename") or f"{manifest['package_id']}.zip",
                        deck.get("deck_title") or "Imported deck",
                        deck.get("subject") or "",
                        str(asset_root / "manifest.json"),
                        int(deck.get("slide_count") or len(deck["slides"])),
                        import_package_id,
                        manifest["package_id"],
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                deck_id = int(deck_cursor.lastrowid)
                deck_ids.append(deck_id)
                for slide_item in deck["slides"]:
                    slide_number = int(slide_item["slide_number"])
                    markdown_path = extract_dir / slide_item["markdown_path"]
                    markdown = markdown_path.read_text(encoding="utf-8")
                    slide_text, explanation = _parse_slide_markdown(markdown)
                    image_path = _copy_import_image(extract_dir, asset_root, slide_item, f"deck-{deck_index}")
                    slide_cursor = conn.execute(
                        """
                        INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text, image_path)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id_int,
                            deck_id,
                            slide_number,
                            slide_item.get("title") or f"Slide {slide_number}",
                            slide_text,
                            image_path,
                        ),
                    )
                    slide_id = int(slide_cursor.lastrowid)
                    conn.execute(
                        """
                        INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
                        VALUES (?, ?, 'imported_share', ?)
                        """,
                        (user_id_int, slide_id, explanation),
                    )
        return {
            "status": "imported",
            "package_id": manifest["package_id"],
            "deck_id": deck_ids[0] if deck_ids else None,
            "deck_ids": deck_ids,
            "deck_count": len(deck_ids),
        }


def _load_and_validate_manifest(extract_dir: Path) -> dict[str, Any]:
    manifest = read_manifest(extract_dir / "manifest.json")
    validate_public_ppt_manifest(manifest)
    for deck in _manifest_decks(manifest):
        for slide in deck["slides"]:
            markdown_path = extract_dir / str(slide.get("markdown_path") or "")
            if not markdown_path.exists() or not markdown_path.is_file():
                raise ValueError(f"slide markdown is missing: {slide.get('markdown_path')}")
            image_path = str(slide.get("image_path") or "")
            if image_path and not (extract_dir / image_path).exists():
                raise ValueError(f"slide image is missing: {image_path}")
    return manifest


def _manifest_decks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    decks = manifest.get("decks")
    if isinstance(decks, list) and decks:
        normalized = []
        for deck in decks:
            if not isinstance(deck, dict):
                continue
            normalized.append(
                {
                    "subject": deck.get("subject") or manifest.get("subject", ""),
                    "deck_title": deck.get("deck_title") or deck.get("title") or manifest.get("deck_title", ""),
                    "filename": deck.get("filename") or f"{manifest['package_id']}.zip",
                    "slide_count": int(deck.get("slide_count") or len(deck.get("slides") or [])),
                    "slides": deck.get("slides") or [],
                }
            )
        return normalized
    slides = manifest.get("slides") or []
    return [
        {
            "subject": manifest.get("subject", ""),
            "deck_title": manifest.get("deck_title", ""),
            "filename": f"{manifest['package_id']}.zip",
            "slide_count": int(manifest.get("slide_count") or len(slides)),
            "slides": slides,
        }
    ]


def _package_has_original(extract_dir: Path) -> bool:
    return any(path.is_file() and path.parent.name == "attachments" for path in extract_dir.rglob("original.*"))


def _preview_deck_title(manifest: dict[str, Any], decks: list[dict[str, Any]]) -> str:
    if "decks" not in manifest:
        return manifest.get("deck_title", "")
    if manifest.get("deck_title"):
        return str(manifest.get("deck_title"))
    if len(decks) == 1:
        return str(decks[0].get("deck_title") or "")
    first_title = str(decks[0].get("deck_title") or "Imported deck")
    return f"{first_title} and {len(decks) - 1} more"


def _existing_package(user_id: int, package_id: str) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT ip.*
        FROM import_packages ip
        WHERE ip.user_id = ?
          AND ip.package_id = ?
          AND EXISTS (
              SELECT 1
              FROM ppt_decks d
              WHERE d.user_id = ip.user_id
                AND (
                    d.import_package_id = ip.id
                    OR d.source_package_id = ip.package_id
                )
          )
        ORDER BY ip.imported_at DESC, ip.id DESC
        LIMIT 1
        """,
        (int(user_id), package_id),
    )


def _materialize_zip(zip_file: Any, target: Path) -> Path:
    if isinstance(zip_file, (str, Path)):
        return Path(zip_file)
    data = bytes(zip_file.getbuffer() if hasattr(zip_file, "getbuffer") else zip_file.read())
    target.write_bytes(data)
    return target


def _copy_import_image(extract_dir: Path, asset_root: Path, slide_item: dict[str, Any], filename_prefix: str = "") -> str:
    image_path = str(slide_item.get("image_path") or "")
    if not image_path:
        return ""
    source = extract_dir / image_path
    if not source.exists():
        return ""
    filename = f"{filename_prefix}-{source.name}" if filename_prefix else source.name
    target = asset_root / "images" / safe_filename(filename, "slide.png")
    shutil.copy2(source, target)
    return str(target)


def _parse_slide_markdown(markdown: str) -> tuple[str, str]:
    content = _strip_frontmatter(markdown)
    slide_text = _section(
        content,
        ["Slide Content", "页面内容", "PPT/PDF 页面文字"],
        stop_headings=SLIDE_TEXT_STOP_HEADINGS,
    )
    explanation = _section(
        content,
        ["AI Explanation", "AI 逐页讲解"],
        stop_headings=EXPLANATION_STOP_HEADINGS,
    )
    return slide_text, explanation


def _strip_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---"):
        return markdown
    lines = markdown.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :]).strip()
    return markdown


def _section(markdown: str, headings: list[str], *, stop_headings: list[str] | None = None) -> str:
    lines = markdown.splitlines()
    start = None
    for index, line in enumerate(lines):
        if _matches_heading(line, headings):
            start = index + 1
            break
    if start is None:
        return markdown.strip()
    end = len(lines)
    for index in range(start, len(lines)):
        if stop_headings is None:
            if lines[index].startswith("## "):
                end = index
                break
            continue
        if _matches_heading(lines[index], stop_headings):
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def _matches_heading(line: str, headings: list[str]) -> bool:
    normalized = line.strip().lower()
    return any(normalized == f"## {heading}".lower() for heading in headings)
