from __future__ import annotations

import hashlib
import os
import stat
import time
from pathlib import Path
from typing import Any

from services import chatgpt_explanation_result_service as result_service
from services import chatgpt_explanation_schema as schema
from services import chatgpt_explanation_task_service as task_service
from services.export_path_service import safe_filename


DEFAULT_STABLE_SECONDS = 2.0
_READ_CHUNK_BYTES = 64 * 1024
_ABSOLUTE_UPLOAD_LIMIT = max(64 * 1024 * 1024, int(schema.MAX_RESULT_BYTES) + 1)
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_TEMPORARY_MARKERS = (
    ".crdownload",
    ".download",
    ".partial",
    ".part",
    ".temp",
    ".tmp",
)


class _FileStillChanging(ValueError):
    pass


def ensure_directories() -> dict[str, Path]:
    bridge_paths = task_service.bridge_directories()
    directories = {key: Path(bridge_paths[key]) for key in ("inbox", "imported", "tasks")}
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def inbox_directory() -> Path:
    return ensure_directories()["inbox"]


def imported_directory() -> Path:
    return ensure_directories()["imported"]


def tasks_directory() -> Path:
    return ensure_directories()["tasks"]


def save_uploaded_result(
    source: Any,
    *,
    filename: str = "explanation_result.json",
    allow_invalid: bool = False,
) -> Path:
    """Save one uploaded JSON file without trusting or reusing its path."""
    limit = _ABSOLUTE_UPLOAD_LIMIT if allow_invalid else int(schema.MAX_RESULT_BYTES)
    payload = _source_bytes(source, limit=limit)
    if len(payload) > limit:
        raise ValueError(f"结果文件过大，最大允许 {limit} 字节")

    safe_name = _safe_json_filename(filename)
    inbox = inbox_directory()
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    for index in range(1, 10_001):
        candidate_name = safe_name if index == 1 else f"{stem}-{index}{suffix}"
        candidate = inbox / candidate_name
        try:
            with candidate.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            return candidate
        except FileExistsError:
            continue
        except Exception:
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
            raise
    raise FileExistsError("Inbox 中同名结果文件过多")


def scan(
    user_id: int,
    *,
    stable_seconds: float = DEFAULT_STABLE_SECONDS,
    auto_import: bool = False,
) -> list[dict[str, Any]]:
    """Preview direct-child JSON results and optionally import complete ones."""
    user_id_int = int(user_id)
    stable_for = max(0.0, float(stable_seconds))
    inbox = inbox_directory()
    items: list[dict[str, Any]] = []

    try:
        candidates = sorted(inbox.iterdir(), key=lambda item: (item.name.casefold(), item.name))
    except OSError as exc:
        return [
            {
                "path": str(inbox),
                "filename": inbox.name,
                "status": "invalid",
                "report": None,
                "errors": [f"无法扫描 Inbox：{exc}"],
            }
        ]

    for path in candidates:
        if not _is_supported_candidate(path):
            continue
        item: dict[str, Any] = {
            "path": str(path),
            "filename": path.name,
            "status": "invalid",
            "report": None,
            "errors": [],
        }
        try:
            before = path.lstat()
            item["size"] = int(before.st_size)
            item["modified_at"] = float(before.st_mtime)
            age = time.time() - float(before.st_mtime)
            if stable_for > 0 and age < stable_for:
                item["status"] = "waiting_stable"
                items.append(item)
                continue

            payload, snapshot = _read_candidate(path, before=before)
            report = result_service.preview_result(user_id_int, payload)
            if not isinstance(report, dict):
                raise ValueError("结果预览服务返回了无效报告")
            item["report"] = report
            item["errors"] = [str(error) for error in report.get("errors", [])]
            item["warnings"] = [str(warning) for warning in report.get("warnings", [])]

            if (
                report.get("already_imported")
                and report.get("duplicate_payload_matches") is True
            ):
                item["status"] = "already_imported"
            elif not report.get("hard_valid"):
                item["status"] = "invalid"
            elif report.get("complete"):
                item["status"] = "ready"
            else:
                item["status"] = "partial"

            if (
                auto_import
                and item["status"] == "ready"
                and report.get("complete") is True
                and report.get("auto_import_allowed") is True
            ):
                outcome = import_inbox_result(
                    user_id_int,
                    path,
                    allow_partial=False,
                    _expected_snapshot=snapshot,
                )
                item["import"] = outcome
                imported_status = str(outcome.get("status") or "invalid")
                item["status"] = (
                    "already_imported" if imported_status == "skipped" else imported_status
                )
                if outcome.get("archive_path"):
                    item["archive_path"] = outcome["archive_path"]
                if outcome.get("archive_error"):
                    item["errors"].append(str(outcome["archive_error"]))
        except _FileStillChanging:
            item["status"] = "waiting_stable"
        except Exception as exc:
            item["status"] = "invalid"
            item["errors"] = [str(exc) or exc.__class__.__name__]
        items.append(item)
    return items


def import_inbox_result(
    user_id: int,
    source: str | os.PathLike[str] | Path,
    *,
    allow_partial: bool = False,
    _expected_snapshot: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    """Atomically import through the result service, then archive the source."""
    user_id_int = int(user_id)
    path = _inbox_source_path(source)
    payload, snapshot = _read_candidate(path)
    if _expected_snapshot is not None and snapshot != _expected_snapshot:
        raise _FileStillChanging("结果文件在预览后发生了变化，请重新扫描")

    report = result_service.preview_result(user_id_int, payload)
    if not isinstance(report, dict) or not report.get("hard_valid"):
        errors = report.get("errors", []) if isinstance(report, dict) else []
        raise ValueError("；".join(str(error) for error in errors) or "结果文件校验失败")

    imported = result_service.import_result(
        user_id_int,
        payload,
        allow_partial=bool(allow_partial),
        source_path=str(path),
    )
    if not isinstance(imported, dict):
        raise ValueError("结果导入服务返回了无效结果")
    outcome = dict(imported)
    destination = _archive_destination(user_id_int, report, outcome)
    outcome["archive_path"] = str(destination)

    status_value = str(outcome.get("status") or "")
    if status_value == "skipped" and outcome.get("duplicate_payload_matches") is not True:
        raise ValueError("重复 result_id 的内容与已导入结果不一致，拒绝归档")
    if status_value == "skipped" and destination.exists():
        outcome["archive_status"] = "already_archived"
        outcome["source_retained"] = path.exists()
        _try_sync_source_path(user_id_int, outcome, destination)
        return outcome
    if status_value not in {"imported", "partial", "skipped"}:
        outcome["archive_status"] = "not_archived"
        outcome["source_retained"] = path.exists()
        return outcome

    try:
        current = path.lstat()
        if _stat_signature(current) != snapshot or stat.S_ISLNK(current.st_mode):
            raise _FileStillChanging("结果文件在导入后发生了变化，已保留在 Inbox")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"归档文件已存在：{destination.name}")
        os.rename(path, destination)
        try:
            archived_payload, _ = _read_candidate(destination)
            if archived_payload != payload:
                raise _FileStillChanging("结果文件在归档前发生了内容变化")
            if not _sync_source_path(user_id_int, outcome, destination):
                raise ValueError("找不到已导入的结果记录")
        except Exception as archive_exc:
            try:
                os.rename(destination, path)
            except Exception as rollback_exc:
                outcome["archive_status"] = "failed"
                outcome["archive_error"] = (
                    "结果文件已移动，但归档校验失败，且无法回滚到 Inbox："
                    f"{archive_exc}；{rollback_exc}"
                )
                outcome["source_retained"] = path.exists()
                _try_sync_source_path(user_id_int, outcome, destination)
                return outcome
            outcome["archive_status"] = "failed"
            outcome["archive_error"] = (
                f"归档校验失败，文件已安全回滚并保留在 Inbox：{archive_exc}"
            )
            outcome["source_retained"] = True
            _try_sync_source_path(user_id_int, outcome, path)
            return outcome
        outcome["archive_status"] = "archived"
        outcome["source_retained"] = False
    except Exception as exc:
        outcome["archive_status"] = "failed"
        outcome["archive_error"] = f"结果已写入，但归档移动失败；原文件已保留：{exc}"
        outcome["source_retained"] = path.exists()
        _try_sync_source_path(user_id_int, outcome, path)
    return outcome


def _source_bytes(source: Any, *, limit: int) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, (bytearray, memoryview)):
        return bytes(source)
    if isinstance(source, str):
        return source.encode("utf-8")

    getter = getattr(source, "getbuffer", None)
    if callable(getter):
        buffer = getter()
        try:
            if len(buffer) > limit:
                return b"x" * (limit + 1)
            return bytes(buffer)
        finally:
            release = getattr(buffer, "release", None)
            if callable(release):
                release()

    getter = getattr(source, "getvalue", None)
    if callable(getter):
        value = getter()
        if isinstance(value, str):
            value = value.encode("utf-8")
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)

    reader = getattr(source, "read", None)
    if not callable(reader):
        raise TypeError("上传结果必须是 bytes 或可读取的文件对象")
    position = None
    teller = getattr(source, "tell", None)
    seeker = getattr(source, "seek", None)
    if callable(teller):
        try:
            position = teller()
        except (OSError, ValueError):
            position = None
    value = reader(limit + 1)
    if position is not None and callable(seeker):
        try:
            seeker(position)
        except (OSError, ValueError):
            pass
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise TypeError("上传文件 read() 必须返回 bytes 或 str")


def _safe_json_filename(filename: object) -> str:
    leaf = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = safe_filename(leaf, "explanation_result.json", max_length=160)
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    if not cleaned.lower().endswith(".json"):
        raise ValueError("只支持 .json 结果文件")
    stem = Path(cleaned).stem.strip(" .")
    if not stem:
        stem = "explanation_result"
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}{Path(cleaned).suffix.lower()}"


def _is_supported_candidate(path: Path) -> bool:
    name = path.name
    lower_name = name.casefold()
    if not name or name.startswith(".") or name.startswith("~") or name.endswith("~"):
        return False
    if path.is_symlink() or path.suffix.casefold() != ".json":
        return False
    if any(
        lower_name.endswith(marker) or f"{marker}." in lower_name
        for marker in _TEMPORARY_MARKERS
    ):
        return False
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _read_candidate(
    path: Path,
    *,
    before: os.stat_result | None = None,
) -> tuple[bytes, tuple[int, int, int, int]]:
    first = before or path.lstat()
    if stat.S_ISLNK(first.st_mode) or not stat.S_ISREG(first.st_mode):
        raise ValueError("只允许读取 Inbox 根目录中的普通 JSON 文件")
    maximum = int(schema.MAX_RESULT_BYTES)
    if first.st_size > maximum:
        raise ValueError(f"结果文件过大，最大允许 {maximum} 字节")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if _stat_signature(opened) != _stat_signature(first) or not stat.S_ISREG(opened.st_mode):
            raise _FileStillChanging("结果文件在打开前发生了变化")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after_read = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    if len(payload) > maximum:
        raise ValueError(f"结果文件过大，最大允许 {maximum} 字节")
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise _FileStillChanging("结果文件在读取期间被移动或删除") from exc
    signature = _stat_signature(first)
    if (
        _stat_signature(after_read) != signature
        or _stat_signature(after_path) != signature
        or stat.S_ISLNK(after_path.st_mode)
    ):
        raise _FileStillChanging("结果文件仍在变化，请稍后重试")
    return payload, signature


def _inbox_source_path(source: str | os.PathLike[str] | Path) -> Path:
    inbox = inbox_directory()
    candidate = Path(source)
    if not candidate.is_absolute() and candidate.parent == Path("."):
        candidate = inbox / candidate.name
    try:
        candidate_parent = candidate.parent.resolve(strict=True)
        inbox_root = inbox.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Inbox 结果文件不存在") from exc
    if candidate_parent != inbox_root:
        raise ValueError("结果文件必须直接位于 Inbox 根目录中")
    if not _is_supported_candidate(candidate):
        raise ValueError("只允许导入 Inbox 根目录中的普通 JSON 文件")
    return candidate


def _archive_destination(
    user_id: int,
    report: dict[str, Any],
    outcome: dict[str, Any],
) -> Path:
    payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}
    task_id = outcome.get("task_id") or report.get("task_id") or payload.get("task_id")
    result_id = outcome.get("result_id") or report.get("result_id") or payload.get("result_id")
    if not task_id or not result_id:
        raise ValueError("导入结果缺少 task_id 或 result_id，无法安全归档")
    safe_task_id = _archive_component(task_id, "task")
    safe_result_id = _archive_component(result_id, "result")
    imported_root = imported_directory().resolve()
    destination = (
        imported_root
        / f"user_{int(user_id)}"
        / safe_task_id
        / f"{safe_result_id}.json"
    )
    destination_resolved = destination.resolve(strict=False)
    common_root = os.path.commonpath([str(imported_root), str(destination_resolved)])
    if os.path.normcase(common_root) != os.path.normcase(str(imported_root)):
        raise ValueError("归档目标路径不安全")
    return destination_resolved


def _archive_component(value: object, fallback: str) -> str:
    """Build a readable, fixed-length and collision-resistant path component."""
    raw = str(value or "")
    readable = safe_filename(raw, fallback, max_length=24)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{readable}-{digest}"


def _sync_source_path(user_id: int, outcome: dict[str, Any], path: Path) -> bool:
    result_id = str(outcome.get("result_id") or "")
    if not result_id:
        raise ValueError("导入结果缺少 result_id，无法更新归档路径")
    return bool(result_service.update_result_source_path(user_id, result_id, str(path)))


def _try_sync_source_path(user_id: int, outcome: dict[str, Any], path: Path) -> None:
    try:
        _sync_source_path(user_id, outcome, path)
    except Exception as exc:
        warning = f"无法同步结果来源路径：{exc}"
        outcome.setdefault("archive_warnings", []).append(warning)


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
    )
