from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from db import DATA_DIR, execute, insert_and_get_id

UPLOAD_DIR = DATA_DIR / "uploads"


def import_pptx(uploaded_file: BinaryIO, *, subject: str, title: str) -> int:
    saved_path = save_uploaded_pptx(uploaded_file)
    slides = extract_pptx_slides(saved_path)
    deck_title = title.strip() or saved_path.stem

    deck_id = insert_and_get_id(
        """
        INSERT INTO ppt_decks (filename, title, subject, file_path, slide_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (saved_path.name, deck_title, subject.strip(), str(saved_path), len(slides)),
    )
    for slide in slides:
        execute(
            """
            INSERT INTO ppt_slides (deck_id, slide_number, title, slide_text, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                deck_id,
                slide["slide_number"],
                slide["title"],
                slide["slide_text"],
                slide["notes"],
            ),
        )
    return deck_id


def save_uploaded_pptx(uploaded_file: BinaryIO) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    original_name = getattr(uploaded_file, "name", "uploaded.pptx")
    suffix = Path(original_name).suffix.lower() or ".pptx"
    safe_stem = _safe_filename(Path(original_name).stem) or "ppt"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = UPLOAD_DIR / f"{timestamp}_{safe_stem}{suffix}"

    data = uploaded_file.getbuffer() if hasattr(uploaded_file, "getbuffer") else uploaded_file.read()
    target.write_bytes(bytes(data))
    return target


def extract_pptx_slides(path: Path) -> list[dict[str, str | int]]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise RuntimeError("未安装 python-pptx，请先运行 pip install -r requirements.txt。") from exc

    presentation = Presentation(path)
    slides: list[dict[str, str | int]] = []
    for index, slide in enumerate(presentation.slides, start=1):
        title = _extract_title(slide)
        text_lines = _extract_text_lines(slide)
        slides.append(
            {
                "slide_number": index,
                "title": title,
                "slide_text": "\n".join(text_lines),
                "notes": "",
            }
        )
    return slides


def _extract_title(slide) -> str:
    if slide.shapes.title and getattr(slide.shapes.title, "text", "").strip():
        return slide.shapes.title.text.strip()
    for line in _extract_text_lines(slide):
        if line.strip():
            return line.strip()[:80]
    return "未命名页面"


def _extract_text_lines(slide) -> list[str]:
    lines: list[str] = []
    for shape in slide.shapes:
        text = getattr(shape, "text", "")
        if not text:
            continue
        for line in text.splitlines():
            clean = line.strip()
            if clean:
                lines.append(clean)
    return lines


def _safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value).strip("._-")

