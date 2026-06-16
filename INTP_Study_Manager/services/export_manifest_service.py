from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


PPT_EXPLANATION_SHARE_TYPE = "ppt_explanation_share"
PPT_EXPLANATION_SHARE_VERSION = "1.0"
PUBLIC_PPT_PRIVACY_MODE = "public_ppt_explanation_only"

PUBLIC_INCLUDED_SECTIONS = ["slide_text", "slide_images", "ai_explanations", "bookmarks", "document_structure"]
PUBLIC_EXCLUDED_SECTIONS = [
    "slide_questions",
    "branch_questions",
    "knowledge_cards",
    "knowledge_links",
    "mistakes",
    "review_tasks",
    "study_sessions",
    "daily_review_logs",
    "daily_ai_review_plans",
    "parking_lot",
    "mastery",
    "api_settings",
    "api_providers",
    "api_keys",
]


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("manifest.json is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("manifest.json is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("manifest.json must contain an object")
    return payload


def validate_public_ppt_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("package_type") != PPT_EXPLANATION_SHARE_TYPE:
        raise ValueError("package_type must be ppt_explanation_share")
    if manifest.get("privacy_mode") != PUBLIC_PPT_PRIVACY_MODE:
        raise ValueError("privacy_mode must be public_ppt_explanation_only")
    slides = manifest.get("slides")
    decks = manifest.get("decks")
    has_slides = isinstance(slides, list) and bool(slides)
    has_decks = isinstance(decks, list) and bool(decks)
    if not has_slides and not has_decks:
        raise ValueError("manifest slides must be a non-empty list")
    if has_decks:
        for deck in decks:
            if not isinstance(deck, Mapping):
                raise ValueError("manifest decks must contain objects")
            deck_slides = deck.get("slides")
            if not isinstance(deck_slides, list) or not deck_slides:
                raise ValueError("manifest deck slides must be a non-empty list")
