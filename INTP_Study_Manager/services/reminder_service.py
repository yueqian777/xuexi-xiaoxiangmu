from __future__ import annotations

import json
import platform
import subprocess
from datetime import date, datetime, time
from typing import Any

from db import BASE_DIR, execute, fetch_one, insert_and_get_id

REMINDER_TASK_NAME = "INTP Study Manager Daily Review"
REMINDER_SCRIPT = BASE_DIR / "scripts" / "daily_review_reminder.ps1"
DEFAULT_REMINDER_CONFIG = {
    "enabled": True,
    "time": "21:00",
}


def get_daily_reminder_config() -> dict[str, Any]:
    row = fetch_one("SELECT value FROM app_settings WHERE key = ?", ("daily_review_reminder",))
    if not row:
        return dict(DEFAULT_REMINDER_CONFIG)
    try:
        config = json.loads(row["value"])
    except json.JSONDecodeError:
        return dict(DEFAULT_REMINDER_CONFIG)
    return {
        "enabled": bool(config.get("enabled", DEFAULT_REMINDER_CONFIG["enabled"])),
        "time": _normalize_time(config.get("time", DEFAULT_REMINDER_CONFIG["time"])),
    }


def save_daily_reminder_config(enabled: bool, reminder_time: time | str) -> None:
    config = {
        "enabled": bool(enabled),
        "time": _normalize_time(reminder_time),
    }
    execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, datetime('now', 'localtime'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        ("daily_review_reminder", json.dumps(config, ensure_ascii=False)),
    )


def get_today_review_log() -> dict[str, Any] | None:
    return fetch_one(
        "SELECT * FROM daily_review_logs WHERE review_date = ?",
        (date.today().isoformat(),),
    )


def mark_today_review_done(notes: str = "") -> int:
    today = date.today().isoformat()
    existing = fetch_one("SELECT id FROM daily_review_logs WHERE review_date = ?", (today,))
    if existing:
        execute(
            """
            UPDATE daily_review_logs
            SET status = '已完成', notes = ?, created_at = datetime('now', 'localtime')
            WHERE review_date = ?
            """,
            (notes, today),
        )
        return int(existing["id"])
    return insert_and_get_id(
        """
        INSERT INTO daily_review_logs (review_date, status, notes)
        VALUES (?, '已完成', ?)
        """,
        (today, notes),
    )


def is_daily_review_due_now(config: dict[str, Any] | None = None) -> bool:
    config = config or get_daily_reminder_config()
    if not config.get("enabled", True):
        return False
    reminder_time = datetime.strptime(config["time"], "%H:%M").time()
    return datetime.now().time() >= reminder_time and get_today_review_log() is None


def install_windows_daily_review_task(reminder_time: time | str) -> tuple[bool, str]:
    if not _is_windows():
        return False, "当前定时提醒安装只支持 Windows。"
    if not REMINDER_SCRIPT.exists():
        return False, f"提醒脚本不存在：{REMINDER_SCRIPT}"

    normalized_time = _normalize_time(reminder_time)
    command = [
        "schtasks",
        "/Create",
        "/TN",
        REMINDER_TASK_NAME,
        "/SC",
        "DAILY",
        "/ST",
        normalized_time,
        "/TR",
        _task_run_command(),
        "/F",
    ]
    return _run_command(command)


def uninstall_windows_daily_review_task() -> tuple[bool, str]:
    if not _is_windows():
        return False, "当前定时提醒卸载只支持 Windows。"
    command = ["schtasks", "/Delete", "/TN", REMINDER_TASK_NAME, "/F"]
    return _run_command(command)


def get_windows_task_status() -> tuple[bool, str]:
    if not _is_windows():
        return False, "非 Windows 环境，无法读取计划任务。"
    command = ["schtasks", "/Query", "/TN", REMINDER_TASK_NAME, "/FO", "LIST", "/V"]
    return _run_command(command)


def run_daily_review_reminder_now() -> tuple[bool, str]:
    if not _is_windows():
        return False, "当前测试提醒只支持 Windows。"
    if not REMINDER_SCRIPT.exists():
        return False, f"提醒脚本不存在：{REMINDER_SCRIPT}"
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REMINDER_SCRIPT),
            ],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return False, str(exc)
    return True, "测试提醒已在后台启动。"


def _normalize_time(value: time | str) -> str:
    if isinstance(value, time):
        return value.strftime("%H:%M")
    text = str(value or DEFAULT_REMINDER_CONFIG["time"]).strip()
    try:
        return datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError:
        return DEFAULT_REMINDER_CONFIG["time"]


def _task_run_command() -> str:
    return f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{REMINDER_SCRIPT}"'


def _run_command(command: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "系统命令执行超时，请稍后在页面中重新查看计划任务状态。"
    except OSError as exc:
        return False, str(exc)

    output = "\n".join(
        part.strip() for part in [completed.stdout, completed.stderr] if part and part.strip()
    )
    return completed.returncode == 0, output or "命令执行完成。"


def _is_windows() -> bool:
    return platform.system().lower() == "windows"
