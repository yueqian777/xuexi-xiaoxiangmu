from __future__ import annotations

import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


WINDOWS_RESERVED_CHARS = r'<>:"/\|?*'


def safe_filename(value: object, fallback: str = "untitled", *, max_length: int = 80) -> str:
    text = str(value or "").strip()
    text = "".join("_" if char in WINDOWS_RESERVED_CHARS or ord(char) < 32 else char for char in text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip(" .-_")
    if not text:
        text = fallback
    return text[:max_length].strip(" .-_") or fallback


def timestamp_slug(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        resolved = path.resolve()
        if resolved.anchor == str(resolved):
            raise ValueError(f"refusing to remove unsafe path: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def zip_directory(source_dir: Path, zip_path: Path) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())
    return zip_path


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
                raise ValueError(f"unsafe absolute path in zip: {info.filename}")
            destination = (target_root / name).resolve()
            if os.path.commonpath([str(target_root), str(destination)]) != str(target_root):
                raise ValueError(f"unsafe path traversal in zip: {info.filename}")
        archive.extractall(target_root)
