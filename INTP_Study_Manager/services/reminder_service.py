from __future__ import annotations

import json
import locale
import platform
import subprocess
from datetime import date, datetime, time
from typing import Any

from db import BASE_DIR, execute, fetch_one, insert_and_get_id
from services.auth_service import require_login

REMINDER_TASK_NAME = "INTP Study Manager Daily Review"
REMINDER_SCRIPT = BASE_DIR / "scripts" / "daily_review_reminder.ps1"
DEFAULT_REMINDER_CONFIG = {
    "enabled": True,
    "time": "21:00",
}


def _user_setting_key(key: str, user_id: int) -> str:
    return f"user:{user_id}:{key}"


def get_daily_reminder_config() -> dict[str, Any]:
    user = require_login()
    row = fetch_one("SELECT value FROM app_settings WHERE key = ?", (_user_setting_key("daily_review_reminder", user.id),))
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
    user = require_login()
    config = {
        "enabled": bool(enabled),
        "time": _normalize_time(reminder_time),
    }
    execute(
        """
        INSERT INTO app_settings (key, user_id, value, updated_at)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(key) DO UPDATE SET
            user_id = excluded.user_id,
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (_user_setting_key("daily_review_reminder", user.id), user.id, json.dumps(config, ensure_ascii=False)),
    )


def get_today_review_log(*, user_id: int | None = None) -> dict[str, Any] | None:
    user_id = user_id if user_id is not None else require_login().id
    return fetch_one(
        "SELECT * FROM daily_review_logs WHERE user_id = ? AND review_date = ?",
        (user_id, date.today().isoformat()),
    )


def mark_today_review_done(notes: str = "") -> int:
    user = require_login()
    today = date.today().isoformat()
    existing = fetch_one("SELECT id FROM daily_review_logs WHERE user_id = ? AND review_date = ?", (user.id, today))
    if existing:
        execute(
            """
            UPDATE daily_review_logs
            SET status = '已完成', notes = ?, created_at = datetime('now', 'localtime')
            WHERE user_id = ? AND review_date = ?
            """,
            (notes, user.id, today),
        )
        return int(existing["id"])
    return insert_and_get_id(
        """
        INSERT INTO daily_review_logs (user_id, review_date, status, notes)
        VALUES (?, ?, '已完成', ?)
        """,
        (user.id, today, notes),
    )


def is_daily_review_due_now(config: dict[str, Any] | None = None, *, user_id: int | None = None) -> bool:
    user_id = user_id if user_id is not None else require_login().id
    config = config or get_daily_reminder_config()
    if not config.get("enabled", True):
        return False
    reminder_time = datetime.strptime(config["time"], "%H:%M").time()
    return datetime.now().time() >= reminder_time and get_today_review_log(user_id=user_id) is None


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
    ok, output = _run_command(command)
    if not ok and _looks_like_missing_task(output):
        return True, "计划任务本来就不存在，无需卸载。"
    return ok, output


def get_windows_task_status() -> tuple[bool, str]:
    if not _is_windows():
        return False, "非 Windows 环境，无法读取计划任务。"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        _scheduled_task_status_script(),
    ]
    ok, output = _run_command(command)
    if not ok and _looks_like_missing_task(output):
        return False, "计划任务尚未安装。点击“安装 / 更新计划任务”即可创建本地每日复盘提醒。"
    if ok:
        return True, _format_windows_task_status(output)
    return ok, output


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


def _scheduled_task_status_script() -> str:
    task_name = REMINDER_TASK_NAME.replace("'", "''")
    return f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$task = Get-ScheduledTask -TaskName '{task_name}'
$info = Get-ScheduledTaskInfo -TaskName '{task_name}'
$action = @($task.Actions)[0]
$trigger = @($task.Triggers)[0]
$result = [ordered]@{{
    TaskName = $task.TaskName
    State = [string]$task.State
    NextRunTime = $(if ($info.NextRunTime) {{ $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ '' }})
    LastRunTime = $(if ($info.LastRunTime) {{ $info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ '' }})
    LastTaskResult = [string]$info.LastTaskResult
    Execute = [string]$action.Execute
    Arguments = [string]$action.Arguments
    TriggerStart = [string]$trigger.StartBoundary
}}
$result | ConvertTo-Json -Compress
"""


def _format_windows_task_status(output: str) -> str:
    output = output.strip().lstrip("﻿")
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return output

    return "\n".join(
        [
            f"任务名：{data.get('TaskName', REMINDER_TASK_NAME)}",
            f"状态：{data.get('State', '')}",
            f"下次运行：{data.get('NextRunTime', '')}",
            f"上次运行：{data.get('LastRunTime', '')}",
            f"上次结果：{data.get('LastTaskResult', '')}",
            f"执行程序：{data.get('Execute', '')}",
            f"执行参数：{data.get('Arguments', '')}",
            f"触发器开始时间：{data.get('TriggerStart', '')}",
        ]
    )
