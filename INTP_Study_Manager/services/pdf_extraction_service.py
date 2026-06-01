from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

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
        backend = os.getenv("INTP_MINERU_BACKEND", "pipeline").strip()
        if backend:
            command.extend(["-b", backend])
        method = os.getenv("INTP_MINERU_METHOD", "").strip()
        if method:
            command.extend(["-m", method])
        lang = os.getenv("INTP_MINERU_LANG", "").strip()
        if lang:
            command.extend(["-l", lang])
        _extend_mineru_optional_cli_args(command)
        environment = os.environ.copy()
        _apply_mineru_local_cache_environment(environment)
        _apply_mineru_device_environment(environment)
        cuda_visible_devices = os.getenv("INTP_MINERU_CUDA_VISIBLE_DEVICES", "0").strip()
        if cuda_visible_devices and "CUDA_VISIBLE_DEVICES" not in environment:
            environment["CUDA_VISIBLE_DEVICES"] = cuda_visible_devices
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(os.getenv("INTP_MINERU_TIMEOUT_SECONDS", "3600")),
            shell=False,
            env=environment,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"MinerU 提取失败：{detail or completed.returncode}")

        content_files = _mineru_content_files(Path(temp_dir))
        if not content_files:
            raise RuntimeError("MinerU 已运行，但没有找到 content_list 输出文件。")
        _archive_mineru_raw_outputs(Path(temp_dir), output_root)
        pages = _parse_richest_mineru_content_files(content_files)
        pages = _offset_mineru_pages_for_configured_range(pages)
        if not pages:
            raise RuntimeError("MinerU 输出为空，未能提取到可用页面内容。")
        return pages


def _mineru_content_files(output_dir: Path) -> list[Path]:
    candidates = list(output_dir.rglob("*_content_list_v2.json"))
    candidates.extend(
        path
        for path in output_dir.rglob("*_content_list.json")
        if not path.name.endswith("_content_list_v2.json")
    )
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def _parse_richest_mineru_content_files(content_files: list[Path]) -> list[dict[str, str | int]]:
    best_pages: list[dict[str, str | int]] = []
    best_score = -1
    for content_file in content_files:
        content = json.loads(content_file.read_text(encoding="utf-8"))
        pages = parse_mineru_content_list(content)
        score = _mineru_pages_score(pages)
        if score > best_score:
            best_pages = pages
            best_score = score
    return best_pages


def _mineru_pages_score(pages: list[dict[str, str | int]]) -> int:
    text = "\n".join(str(page.get("slide_text") or "") for page in pages)
    math_bonus = text.count("$$") * 20 + text.count("\\") * 2
    return len(pages) * 1000 + len(text.strip()) + math_bonus


def _offset_mineru_pages_for_configured_range(pages: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    start = _configured_mineru_start_page()
    if start <= 0:
        return pages
    if pages and min(int(page["slide_number"]) for page in pages) >= start + 1:
        return pages
    return [
        {
            **page,
            "slide_number": int(page["slide_number"]) + start,
        }
        for page in pages
    ]


def _configured_mineru_start_page() -> int:
    value = os.getenv("INTP_MINERU_START_PAGE", "").strip()
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _archive_mineru_raw_outputs(temp_dir: Path, output_root: Path) -> None:
    if os.getenv("INTP_MINERU_ARCHIVE_RAW_OUTPUT", "1").strip().lower() in {"0", "false", "no"}:
        return
    archive_dir = output_root / "_raw" / temp_dir.name
    archive_dir.mkdir(parents=True, exist_ok=True)
    for source in temp_dir.rglob("*"):
        if not source.is_file() or source.suffix.lower() not in {".json", ".md"}:
            continue
        relative = source.relative_to(temp_dir)
        destination = archive_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _mineru_output_root(path: Path) -> Path:
    configured = os.getenv("INTP_MINERU_OUTPUT_DIR", "").strip()
    if configured:
        return Path(configured)
    return DATA_DIR / "mineru_outputs" / _safe_filename(path.stem)


def _apply_mineru_local_cache_environment(environment: dict[str, str]) -> None:
    cache_root = Path(os.getenv("INTP_MINERU_CACHE_DIR", "D:/MinerU/cache"))
    temp_root = Path(os.getenv("INTP_MINERU_TEMP_DIR", "D:/MinerU/tmp"))
    cache_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    for key, value in {
        "TEMP": str(temp_root),
        "TMP": str(temp_root),
        "HF_HOME": str(cache_root / "huggingface"),
        "HUGGINGFACE_HUB_CACHE": str(cache_root / "huggingface" / "hub"),
        "TRANSFORMERS_CACHE": str(cache_root / "transformers"),
        "MODELSCOPE_CACHE": str(cache_root / "modelscope"),
    }.items():
        environment.setdefault(key, value)

    model_source = os.getenv("INTP_MINERU_MODEL_SOURCE", "modelscope").strip()
    if model_source:
        environment.setdefault("MINERU_MODEL_SOURCE", model_source)

    for env_key, mineru_key, default in (
        ("INTP_MINERU_FORMULA", "MINERU_FORMULA_ENABLE", "true"),
        ("INTP_MINERU_TABLE", "MINERU_TABLE_ENABLE", "true"),
    ):
        value = os.getenv(env_key, default).strip()
        if value:
            environment.setdefault(mineru_key, value)


def _apply_mineru_device_environment(environment: dict[str, str]) -> None:
    device_mode = os.getenv("INTP_MINERU_DEVICE_MODE", "cuda").strip()
    if device_mode and "MINERU_DEVICE_MODE" not in environment:
        environment["MINERU_DEVICE_MODE"] = device_mode

    for key, value in {
        "MINERU_PROCESSING_WINDOW_SIZE": os.getenv("INTP_MINERU_PROCESSING_WINDOW_SIZE", "16").strip(),
        "MINERU_API_MAX_CONCURRENT_REQUESTS": os.getenv("INTP_MINERU_API_MAX_CONCURRENT_REQUESTS", "1").strip(),
    }.items():
        if value and key not in environment:
            environment[key] = value


def _extend_mineru_optional_cli_args(command: list[str]) -> None:
    for env_key, cli_key in (
        ("INTP_MINERU_START_PAGE", "--start"),
        ("INTP_MINERU_END_PAGE", "--end"),
    ):
        value = os.getenv(env_key, "").strip()
        if value:
            command.extend([cli_key, value])

    for env_key, cli_key, default in (
        ("INTP_MINERU_FORMULA", "--formula", "true"),
        ("INTP_MINERU_TABLE", "--table", "true"),
        ("INTP_MINERU_IMAGE_ANALYSIS", "--image-analysis", ""),
    ):
        value = os.getenv(env_key, default).strip()
        if value:
            command.extend([cli_key, value])


def _parse_mineru_content_list_v1(content: list[Any]) -> list[dict[str, str | int]]:
    pages: dict[int, list[str]] = {}
    for item in content:
        if not isinstance(item, dict):
            continue
        page_number = _mineru_v1_page_number(item)
        block = _mineru_v1_block_to_text(item)
        if block:
            pages.setdefault(page_number, []).append(block)
    return _pages_from_grouped_text(pages)


def _mineru_v1_page_number(item: dict[str, Any]) -> int:
    if "page_idx" in item:
        return _safe_int(item.get("page_idx"), default=0) + 1
    for key in ("page", "page_no", "page_number", "page_id"):
        if key in item:
            value = _safe_int(item.get(key), default=1)
            return value + 1 if value <= 0 else value
    return 1


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
    if block_type in {"text", "title", "header", "footer", "page_header", "page_footer"}:
        text = normalize_mineru_math_text(str(item.get("text") or "").strip())
        level = int(item.get("text_level") or 0)
        if text and level > 0:
            return f"{'#' * min(level, 6)} {text}"
        return text
    if block_type == "equation":
        return _mathjax_display_formula(str(item.get("text") or ""))
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
    return _fallback_mineru_block_text(item)


def _mineru_v2_block_to_text(item: dict[str, Any]) -> str:
    block_type = str(item.get("type") or "")
    content = item.get("content") or {}
    if block_type == "title":
        text = _span_text(content.get("title_content") or content.get("content"))
        level = _mineru_heading_level(content.get("level"))
        return f"{'#' * min(level, 6)} {text}".strip()
    if block_type == "paragraph":
        return normalize_mineru_math_text(_span_text(content.get("paragraph_content") or content.get("content")))
    if block_type == "equation_interline":
        return _mathjax_display_formula(str(content.get("math_content") or content.get("content") or ""))
    if block_type in {"table", "image", "chart"}:
        parts = [
            _span_text(content.get("table_caption") or content.get("image_caption") or content.get("chart_caption")),
            _span_text(content.get("table_body") or content.get("content")),
            _span_text(content.get("table_footnote") or content.get("image_footnote") or content.get("chart_footnote")),
        ]
        return "\n\n".join(part for part in parts if part)
    if block_type in {"list", "index"}:
        items = content.get("list_items") or content.get("index_items") or []
        return "\n".join(f"- {_span_text(item)}" for item in items if _span_text(item))
    if block_type in {"code", "algorithm"}:
        return _span_text(content.get("code_content") or content.get("algorithm_content"))
    if block_type in {"page_header", "page_footer", "header", "footer"}:
        return _span_text(
            content.get("page_header_content")
            or content.get("page_footer_content")
            or content.get("header_content")
            or content.get("footer_content")
            or content.get("content")
        )
    return _fallback_mineru_block_text(content if isinstance(content, dict) else item)


def _fallback_mineru_block_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "text",
        "content",
        "body",
        "caption",
        "html",
        "math_content",
        "math_latex",
        "latex",
        "markdown",
        "paragraph_content",
        "title_content",
        "spans",
    ):
        value = item.get(key)
        text = _span_text(value)
        if text:
            parts.append(normalize_mineru_math_text(text))
    return "\n\n".join(dict.fromkeys(parts))


def _mineru_heading_level(value: Any) -> int:
    if value is None:
        return 1
    parsed = _safe_int(value, default=0)
    if parsed > 0:
        return parsed
    match = re.search(r"\d+", str(value))
    return max(1, int(match.group(0))) if match else 1


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _span_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if "content" in value:
            return _span_text(value.get("content"))
        if "text" in value:
            return _span_text(value.get("text"))
        if "math_content" in value:
            return _span_text(value.get("math_content"))
        if "math_latex" in value:
            return _span_text(value.get("math_latex"))
        if "latex" in value:
            return _span_text(value.get("latex"))
        return " ".join(_span_text(item) for item in value.values()).strip()
    if isinstance(value, list):
        return _join_span_parts(_span_text(item) for item in value)
    return str(value).strip()


def _join_span_parts(parts: Iterable[str]) -> str:
    text = ""
    for part in (value.strip() for value in parts):
        if not part:
            continue
        if text and _needs_space_between_fragments(text[-1], part[0]):
            text += " "
        text += part
    return text.strip()


def _needs_space_between_fragments(left: str, right: str) -> bool:
    if left.isspace() or right.isspace():
        return False
    if left in "([{/$\\" or right in ")]}.,;:!?，。；：、）】》":
        return False
    if _is_cjk(left) or _is_cjk(right):
        return False
    return left.isalnum() and right.isalnum()


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _mathjax_display_formula(value: str) -> str:
    text = _strip_wrapping_math_delimiters(value.strip())
    if not text:
        return ""
    return f"$${text}$$"


def _mathjax_inline_formula(value: str) -> str:
    text = _strip_wrapping_math_delimiters(value.strip())
    if not text:
        return ""
    return f"${text}$"


def _strip_wrapping_math_delimiters(text: str) -> str:
    if text.startswith(r"\[") and text.endswith(r"\]"):
        return text[2:-2].strip()
    if text.startswith(r"\(") and text.endswith(r"\)"):
        return text[2:-2].strip()
    if text.startswith("$") or text.endswith("$"):
        stripped = text.strip("$").strip()
        return stripped or text
    return text


_LATEX_COMMAND_PATTERN = re.compile(r"\\[A-Za-z]+")
_LATEX_INLINE_SEGMENT_PATTERN = re.compile(
    r"\\[A-Za-z]+"
    r"(?:\s*(?:[_^]\s*\{[^{}]*\}|[_^]\s*[A-Za-z0-9]+|\{[^{}]*\}|[=+\-*/(),.\[\]A-Za-z0-9])+)*"
)
_LATEX_SYMBOL_PATTERN = re.compile(r"(?:\\[A-Za-z]+|[_^]\s*\{|[=<>])")


def normalize_mineru_math_text(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    return _normalize_latex_outside_existing_math(text)


def _normalize_latex_outside_existing_math(text: str) -> str:
    output: list[str] = []
    index = 0
    plain_start = 0
    while index < len(text):
        span = _normalized_math_span_at(text, index)
        if span:
            end_index, normalized = span
            output.append(_wrap_bare_latex_segments(text[plain_start:index]))
            output.append(normalized)
            index = end_index
            plain_start = index
            continue
        index += 1
    output.append(_wrap_bare_latex_segments(text[plain_start:]))
    return "".join(output)


def _normalized_math_span_at(text: str, index: int) -> tuple[int, str] | None:
    if text.startswith(r"\[", index):
        end = _find_unescaped_token(text, r"\]", index + 2)
        if end >= 0:
            return end + 2, _mathjax_display_formula(text[index : end + 2])
    if text.startswith(r"\(", index):
        end = _find_unescaped_token(text, r"\)", index + 2)
        if end >= 0:
            return end + 2, _mathjax_inline_formula(text[index : end + 2])

    dollar_count = _dollar_run_length(text, index)
    if dollar_count >= 2:
        content_start = index + dollar_count
        end = _find_dollar_run(text, content_start, min_count=2)
        if end >= 0:
            return end + _dollar_run_length(text, end), _mathjax_display_formula(text[content_start:end])
        line_end = _line_end_index(text, content_start)
        candidate = text[content_start:line_end]
        if _contains_latex(candidate):
            return line_end, _mathjax_display_formula(candidate)
    if dollar_count == 1:
        content_start = index + 1
        end = _find_dollar_run(text, content_start, min_count=1, exact_count=1)
        if end >= 0:
            return end + 1, _mathjax_inline_formula(text[content_start:end])
        line_end = _line_end_index(text, content_start)
        candidate = text[content_start:line_end]
        if _contains_latex(candidate):
            return line_end, _mathjax_inline_formula(candidate)
    return None


def _wrap_bare_latex_segments(text: str) -> str:
    if not _LATEX_COMMAND_PATTERN.search(text):
        return text
    stripped = text.strip()
    if stripped and _looks_like_standalone_latex(stripped):
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()) :]
        return f"{leading}{_mathjax_display_formula(stripped)}{trailing}"
    return _LATEX_INLINE_SEGMENT_PATTERN.sub(
        lambda match: _mathjax_inline_formula(match.group(0).strip()),
        text,
    )


def _contains_latex(text: str) -> bool:
    return bool(_LATEX_SYMBOL_PATTERN.search(text))


def _find_unescaped_token(text: str, token: str, start: int) -> int:
    index = start
    while index < len(text):
        found = text.find(token, index)
        if found < 0:
            return -1
        if not _is_escaped(text, found):
            return found
        index = found + len(token)
    return -1


def _dollar_run_length(text: str, index: int) -> int:
    if index >= len(text) or text[index] != "$" or _is_escaped(text, index):
        return 0
    end = index
    while end < len(text) and text[end] == "$":
        end += 1
    return end - index


def _find_dollar_run(text: str, start: int, *, min_count: int, exact_count: int | None = None) -> int:
    index = start
    while index < len(text):
        run_length = _dollar_run_length(text, index)
        if run_length:
            if run_length >= min_count and (exact_count is None or run_length == exact_count):
                return index
            index += run_length
            continue
        index += 1
    return -1


def _line_end_index(text: str, start: int) -> int:
    newline = text.find("\n", start)
    return len(text) if newline < 0 else newline


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _looks_like_standalone_latex(text: str) -> bool:
    if any(char in text for char in "，。；：、！？"):
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    return bool(
        "=" in text
        or r"\begin" in text
        or r"\frac" in text
        or r"\sqrt" in text
        or r"\sum" in text
        or r"\prod" in text
    )


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
