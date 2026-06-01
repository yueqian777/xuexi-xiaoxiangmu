from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from db import DATA_DIR


@dataclass(frozen=True)
class MinerUStatus:
    available: bool
    command: str
    message: str


def extract_pdf_pages(path: Path, *, method: str = "local") -> list[dict[str, str | int]]:
    if method == "mineru":
        return _extract_pdf_pages_with_mineru(path)
    return _extract_pdf_pages_locally(path)


def get_mineru_status() -> MinerUStatus:
    configured = os.getenv("INTP_MINERU_COMMAND", "").strip().strip('"')
    if configured:
        resolved = _resolve_command(configured)
        if resolved:
            return _mineru_status_from_resolved_command(resolved, "已找到 INTP_MINERU_COMMAND 指向的 MinerU")
        return MinerUStatus(
            False,
            configured,
            f"INTP_MINERU_COMMAND 指向的 MinerU 命令不可用：{configured}",
        )

    default_path = Path("D:/MinerU/.venv/Scripts/mineru.exe")
    if default_path.exists():
        return _mineru_status_from_resolved_command(str(default_path), "已找到 D:\\MinerU\\.venv\\Scripts\\mineru.exe")

    resolved = shutil.which("mineru")
    if resolved:
        return _mineru_status_from_resolved_command(resolved, "已找到 PATH 中的 MinerU")

    return MinerUStatus(
        False,
        "",
        "未检测到 MinerU。可选安装后设置 INTP_MINERU_COMMAND，或使用 D:\\MinerU\\.venv\\Scripts\\mineru.exe。",
    )


def _mineru_status_from_resolved_command(command: str, source_message: str) -> MinerUStatus:
    usable, detail = _probe_mineru_command(command)
    if usable:
        return MinerUStatus(True, command, f"已检测到 MinerU：{command}")
    return MinerUStatus(
        False,
        command,
        f"{source_message}，但 MinerU 命令无法运行：{detail}",
    )


def parse_mineru_content_list(content: Any) -> list[dict[str, str | int]]:
    if not isinstance(content, list):
        return []
    if content and all(isinstance(page, list) for page in content):
        return _parse_mineru_content_list_v2(content)
    return _parse_mineru_content_list_v1(content)


def _extract_pdf_pages_locally(path: Path) -> list[dict[str, str | int]]:
    extracted_by_page: dict[int, tuple[str, str]] = {}
    extracted_by_page.update(_extract_pdf_text_with_pdfplumber(path))

    pypdf_text = _extract_pdf_text_with_pypdf(path)
    for page_number, text in pypdf_text.items():
        if page_number not in extracted_by_page and text.strip():
            extracted_by_page[page_number] = (text.strip(), "local:pypdf")

    fitz_text = _extract_pdf_text_with_fitz(path)
    for page_number, text in fitz_text.items():
        if page_number not in extracted_by_page and text.strip():
            extracted_by_page[page_number] = (text.strip(), "local:fitz")

    page_count = max(
        [0, *extracted_by_page.keys(), *pypdf_text.keys(), *fitz_text.keys()],
    )
    pages: list[dict[str, str | int]] = []
    for page_number in range(1, page_count + 1):
        text, extractor = extracted_by_page.get(page_number, ("", "local:none"))
        title = _first_text_line(text) or f"PDF 第 {page_number} 页"
        pages.append(
            {
                "slide_number": page_number,
                "title": title[:80],
                "slide_text": text,
                "notes": f"source=pdf;extractor={extractor}",
            }
        )
    return pages


def _extract_pdf_text_with_pdfplumber(path: Path) -> dict[int, tuple[str, str]]:
    try:
        import pdfplumber
    except ImportError:
        return {}

    result: dict[int, tuple[str, str]] = {}
    try:
        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                try:
                    chunks: list[str] = []
                    text = (page.extract_text(x_tolerance=2, y_tolerance=3) or "").strip()
                    if text:
                        chunks.append(text)
                    table = page.extract_table()
                    table_markdown = _markdown_table(table)
                    if table_markdown:
                        chunks.append(table_markdown)
                    if chunks:
                        result[index] = ("\n\n".join(chunks), "local:pdfplumber")
                finally:
                    close = getattr(page, "close", None)
                    if callable(close):
                        close()
    except Exception:
        return {}
    return result


def _extract_pdf_text_with_pypdf(path: Path) -> dict[int, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return {}

    result: dict[int, str] = {}
    try:
        reader = PdfReader(str(path))
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            result[index] = text
    except Exception:
        return result
    return result


def _extract_pdf_text_with_fitz(path: Path) -> dict[int, str]:
    try:
        import fitz
    except ImportError:
        return {}

    result: dict[int, str] = {}
    try:
        document = fitz.open(path)
    except Exception:
        return {}
    try:
        for index, page in enumerate(document, start=1):
            text = (page.get_text("text") or "").strip()
            result[index] = text
    finally:
        document.close()
    return result


def _extract_pdf_pages_with_mineru(path: Path) -> list[dict[str, str | int]]:
    status = get_mineru_status()
    if not status.available:
        raise RuntimeError(status.message)

    output_root = _mineru_output_root(path)
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mineru_", dir=str(output_root)) as temp_dir:
        command = [
            status.command,
            "-p",
            str(path),
            "-o",
            temp_dir,
        ]
        backend = os.getenv("INTP_MINERU_BACKEND", "").strip()
        if backend:
            command.extend(["-b", backend])
        method = os.getenv("INTP_MINERU_METHOD", "").strip()
        if method:
            command.extend(["-m", method])
        lang = os.getenv("INTP_MINERU_LANG", "").strip()
        if lang:
            command.extend(["-l", lang])
        environment = os.environ.copy()
        cuda_visible_devices = os.getenv("INTP_MINERU_CUDA_VISIBLE_DEVICES", "").strip()
        if cuda_visible_devices:
            environment["CUDA_VISIBLE_DEVICES"] = cuda_visible_devices
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("INTP_MINERU_TIMEOUT_SECONDS", "3600")),
            shell=False,
            env=environment,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"MinerU 提取失败：{detail or completed.returncode}")

        content_file = _latest_mineru_content_file(Path(temp_dir))
        if not content_file:
            raise RuntimeError("MinerU 已运行，但没有找到 content_list 输出文件。")
        content = json.loads(content_file.read_text(encoding="utf-8"))
        pages = parse_mineru_content_list(content)
        if not pages:
            raise RuntimeError("MinerU 输出为空，未能提取到可用页面内容。")
        return pages


def _latest_mineru_content_file(output_dir: Path) -> Path | None:
    candidates = list(output_dir.rglob("*_content_list_v2.json"))
    if not candidates:
        candidates = list(output_dir.rglob("*_content_list.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _mineru_output_root(path: Path) -> Path:
    configured = os.getenv("INTP_MINERU_OUTPUT_DIR", "").strip()
    if configured:
        return Path(configured)
    return DATA_DIR / "mineru_outputs" / _safe_filename(path.stem)


def _parse_mineru_content_list_v1(content: list[Any]) -> list[dict[str, str | int]]:
    pages: dict[int, list[str]] = {}
    for item in content:
        if not isinstance(item, dict):
            continue
        page_number = int(item.get("page_idx") or 0) + 1
        block = _mineru_v1_block_to_text(item)
        if block:
            pages.setdefault(page_number, []).append(block)
    return _pages_from_grouped_text(pages)


def _parse_mineru_content_list_v2(content: list[Any]) -> list[dict[str, str | int]]:
    pages: dict[int, list[str]] = {}
    for index, page_items in enumerate(content, start=1):
        if not isinstance(page_items, list):
            continue
        for item in page_items:
            if not isinstance(item, dict):
                continue
            block = _mineru_v2_block_to_text(item)
            if block:
                pages.setdefault(index, []).append(block)
    return _pages_from_grouped_text(pages)


def _pages_from_grouped_text(pages: dict[int, list[str]]) -> list[dict[str, str | int]]:
    result: list[dict[str, str | int]] = []
    for page_number in sorted(pages):
        text = "\n\n".join(chunk for chunk in pages[page_number] if chunk.strip()).strip()
        title = _first_text_line(text) or f"PDF 第 {page_number} 页"
        result.append(
            {
                "slide_number": page_number,
                "title": title[:80],
                "slide_text": text,
                "notes": "source=pdf;extractor=mineru",
            }
        )
    return result


def _mineru_v1_block_to_text(item: dict[str, Any]) -> str:
    block_type = str(item.get("type") or "")
    if block_type in {"text", "title"}:
        text = str(item.get("text") or "").strip()
        level = int(item.get("text_level") or 0)
        if text and level > 0:
            return f"{'#' * min(level, 6)} {text}"
        return text
    if block_type == "equation":
        return str(item.get("text") or "").strip()
    if block_type == "table":
        return "\n\n".join(
            chunk
            for chunk in [
                "\n".join(str(value) for value in item.get("table_caption") or []),
                str(item.get("table_body") or "").strip(),
                "\n".join(str(value) for value in item.get("table_footnote") or []),
            ]
            if chunk.strip()
        )
    if block_type == "list":
        items = item.get("list_items") or []
        return "\n".join(f"- {value}" for value in items if str(value).strip())
    if block_type in {"image", "chart"}:
        captions = item.get("image_caption") or item.get("chart_caption") or []
        body = item.get("content") or ""
        return "\n".join([*(str(value) for value in captions), str(body)]).strip()
    if block_type == "code":
        return str(item.get("code_body") or "").strip()
    return ""


def _mineru_v2_block_to_text(item: dict[str, Any]) -> str:
    block_type = str(item.get("type") or "")
    content = item.get("content") or {}
    if block_type == "title":
        text = _span_text(content.get("title_content") or content.get("content"))
        level = int(content.get("level") or 1)
        return f"{'#' * min(level, 6)} {text}".strip()
    if block_type == "paragraph":
        return _span_text(content.get("paragraph_content") or content.get("content"))
    if block_type == "equation_interline":
        return str(content.get("math_content") or content.get("content") or "").strip()
    if block_type in {"table", "image", "chart"}:
        parts = [
            _span_text(content.get("table_caption") or content.get("image_caption") or content.get("chart_caption")),
            str(content.get("table_body") or content.get("content") or "").strip(),
            _span_text(content.get("table_footnote") or content.get("image_footnote") or content.get("chart_footnote")),
        ]
        return "\n\n".join(part for part in parts if part)
    if block_type in {"list", "index"}:
        items = content.get("list_items") or content.get("index_items") or []
        return "\n".join(f"- {_span_text(item)}" for item in items if _span_text(item))
    if block_type in {"code", "algorithm"}:
        return str(content.get("code_content") or content.get("algorithm_content") or "").strip()
    return ""


def _span_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if "content" in value:
            return _span_text(value.get("content"))
        return " ".join(_span_text(item) for item in value.values()).strip()
    if isinstance(value, list):
        return "".join(_span_text(item) for item in value).strip()
    return str(value).strip()


def _markdown_table(table: Any) -> str:
    if not table:
        return ""
    rows = [[str(cell or "").strip() for cell in row] for row in table if row]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return ""
    widths = [max(len(row[index]) if index < len(row) else 0 for row in rows) for index in range(max(len(row) for row in rows))]

    def format_row(row: list[str]) -> str:
        cells = [row[index] if index < len(row) else "" for index in range(len(widths))]
        return "| " + " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)) + " |"

    header = format_row(rows[0])
    separator = "| " + " | ".join("-" * max(3, width) for width in widths) + " |"
    body = [format_row(row) for row in rows[1:]]
    return "\n".join([header, separator, *body])


def _first_text_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean
    return ""


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-") or "pdf"


def _resolve_command(command: str) -> str | None:
    command_path = Path(command)
    if command_path.exists():
        return str(command_path)
    resolved = shutil.which(command)
    return resolved


@lru_cache(maxsize=8)
def _probe_mineru_command(command: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [command, "--help"],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
    except Exception as exc:
        return False, str(exc)

    detail = (completed.stderr or completed.stdout or "").strip()
    if completed.returncode == 0:
        return True, detail.splitlines()[0] if detail else "ok"
    return False, detail or f"exit code {completed.returncode}"
