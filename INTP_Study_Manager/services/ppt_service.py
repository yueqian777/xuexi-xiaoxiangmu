from __future__ import annotations

import subprocess
import re
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from db import DATA_DIR, execute, insert_and_get_id

UPLOAD_DIR = DATA_DIR / "uploads"
PAGE_IMAGE_DIR = DATA_DIR / "page_images"


def import_deck(uploaded_file: BinaryIO, *, subject: str, title: str) -> int:
    original_name = getattr(uploaded_file, "name", "")
    suffix = Path(original_name).suffix.lower()
    if suffix == ".pptx":
        return import_pptx(uploaded_file, subject=subject, title=title)
    if suffix == ".pdf":
        return import_pdf(uploaded_file, subject=subject, title=title)
    raise RuntimeError("仅支持 PPTX 或 PDF 文件。")


def import_pptx(uploaded_file: BinaryIO, *, subject: str, title: str) -> int:
    saved_path = save_uploaded_deck(uploaded_file)
    slides = extract_pptx_slides(saved_path)
    image_paths = render_deck_page_images(saved_path)
    return _save_deck_records(saved_path, slides, image_paths, subject=subject, title=title)


def import_pdf(uploaded_file: BinaryIO, *, subject: str, title: str) -> int:
    saved_path = save_uploaded_deck(uploaded_file)
    slides = extract_pdf_pages(saved_path)
    image_paths = render_deck_page_images(saved_path)
    return _save_deck_records(saved_path, slides, image_paths, subject=subject, title=title)


def _save_deck_records(
    saved_path: Path,
    slides: list[dict[str, str | int]],
    image_paths: dict[int, Path],
    *,
    subject: str,
    title: str,
) -> int:
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
            INSERT INTO ppt_slides (deck_id, slide_number, title, slide_text, notes, image_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                deck_id,
                slide["slide_number"],
                slide["title"],
                slide["slide_text"],
                slide["notes"],
                str(image_paths.get(int(slide["slide_number"]), "")),
            ),
        )
    return deck_id


def save_uploaded_deck(uploaded_file: BinaryIO) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    original_name = getattr(uploaded_file, "name", "uploaded")
    suffix = Path(original_name).suffix.lower() or ".pptx"
    safe_stem = _safe_filename(Path(original_name).stem) or "deck"
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


def extract_pdf_pages(path: Path) -> list[dict[str, str | int]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("未安装 pypdf，请先运行 pip install -r requirements.txt。") from exc

    reader = PdfReader(str(path))
    fitz_text_by_page = _extract_pdf_text_with_fitz(path)
    slides: list[dict[str, str | int]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            text = fitz_text_by_page.get(index, "")
        title = _first_text_line(text) or f"PDF 第 {index} 页"
        slides.append(
            {
                "slide_number": index,
                "title": title[:80],
                "slide_text": text,
                "notes": "source=pdf",
            }
        )
    return slides


def _extract_pdf_text_with_fitz(path: Path) -> dict[int, str]:
    try:
        import fitz
    except ImportError:
        return {}

    result: dict[int, str] = {}
    document = fitz.open(path)
    try:
        for index, page in enumerate(document, start=1):
            text = (page.get_text("text") or "").strip()
            if text:
                result[index] = text
    finally:
        document.close()
    return result


def render_deck_page_images(path: Path) -> dict[int, Path]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return render_pdf_page_images(path)
    if suffix == ".pptx":
        return render_pptx_page_images(path)
    raise RuntimeError("仅支持渲染 PDF 或 PPTX。")


def render_pdf_page_images(path: Path) -> dict[int, Path]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("未安装 PyMuPDF，请先运行 pip install -r requirements.txt。") from exc

    target_dir = _page_image_target_dir(path)
    target_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(path)
    result: dict[int, Path] = {}
    matrix = fitz.Matrix(2, 2)
    for index, page in enumerate(document, start=1):
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        target = target_dir / f"page_{index:03d}.png"
        pixmap.save(target)
        result[index] = target
    document.close()
    return result


def render_pptx_page_images(path: Path) -> dict[int, Path]:
    target_dir = _page_image_target_dir(path)
    target_dir.mkdir(parents=True, exist_ok=True)

    script = f"""
$ErrorActionPreference = 'Stop'
$pptPath = {str(path.resolve())!r}
$outDir = {str(target_dir.resolve())!r}
$app = New-Object -ComObject PowerPoint.Application
try {{
    $presentation = $app.Presentations.Open($pptPath, $false, $false, $false)
    try {{
        $presentation.Export($outDir, 'PNG', 1440, 810)
    }} finally {{
        $presentation.Close()
    }}
}} finally {{
    $app.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
}}
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"PowerPoint 导出页面图片失败：{completed.stderr or completed.stdout}")

    result: dict[int, Path] = {}
    for image in target_dir.glob("*.PNG"):
        index = _slide_image_index(image.name)
        if index:
            normalized = target_dir / f"page_{index:03d}.png"
            if image != normalized:
                image.replace(normalized)
            result[index] = normalized
    for image in target_dir.glob("*.png"):
        index = _slide_image_index(image.name)
        if index:
            result[index] = image
    if not result:
        raise RuntimeError("PowerPoint 导出完成，但未找到页面图片。")
    return result


def render_missing_page_images(deck: dict, slides: list[dict]) -> dict[int, Path]:
    path = Path(deck["file_path"])
    image_paths = render_deck_page_images(path)
    for slide in slides:
        slide_number = int(slide["slide_number"])
        image_path = image_paths.get(slide_number)
        if image_path:
            execute(
                "UPDATE ppt_slides SET image_path = ? WHERE id = ?",
                (str(image_path), slide["id"]),
            )
    return image_paths


def refresh_pdf_slide_text(deck: dict, slides: list[dict]) -> int:
    path = Path(deck["file_path"])
    if path.suffix.lower() != ".pdf":
        raise RuntimeError("只有 PDF 资料需要重新提取文字。")

    extracted = {int(item["slide_number"]): item for item in extract_pdf_pages(path)}
    updated = 0
    for slide in slides:
        slide_number = int(slide["slide_number"])
        item = extracted.get(slide_number)
        if not item:
            continue
        execute(
            """
            UPDATE ppt_slides
            SET title = ?, slide_text = ?, notes = ?
            WHERE id = ?
            """,
            (
                item["title"],
                item["slide_text"],
                item["notes"],
                slide["id"],
            ),
        )
        if str(item["slide_text"]).strip():
            updated += 1
    return updated


def _page_image_target_dir(path: Path) -> Path:
    return PAGE_IMAGE_DIR / _safe_filename(path.stem)


def _slide_image_index(filename: str) -> int | None:
    match = re.search(r"(\d+)", filename)
    return int(match.group(1)) if match else None


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


def _first_text_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return ""


def _safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value).strip("._-")
