from __future__ import annotations

import json
import locale
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
    output = output.strip().lstrip("\ufeff")
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


def _run_command(command: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "系统命令执行超时，请稍后在页面中重新查看计划任务状态。"
    except OSError as exc:
        return False, str(exc)

    output = "\n".join(
        part.strip()
        for part in [
            _decode_command_output(completed.stdout),
            _decode_command_output(completed.stderr),
        ]
        if part and part.strip()
    )
    return completed.returncode == 0, output or "命令执行完成。"


def _decode_command_output(data: bytes) -> str:
    if not data:
        return ""

    preferred = locale.getpreferredencoding(False)
    encodings = ["utf-8-sig", "utf-8", preferred, "mbcs", "gbk", "cp936"]
    tried: set[str] = set()
    for encoding in encodings:
        if not encoding or encoding in tried:
            continue
        tried.add(encoding)
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode(preferred or "utf-8", errors="replace")


def _looks_like_missing_task(output: str) -> bool:
    normalized = output.lower()
    return any(
        marker in normalized
        for marker in [
            "cannot find the file specified",
            "找不到指定的文件",
            "任务不存在",
            "does not exist",
            "no msft_scheduledtask objects found",
            "no scheduled task was found",
        ]
    )


def _is_windows() -> bool:
    return platform.system().lower() == "windows"
