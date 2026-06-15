from __future__ import annotations

import json
import platform
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from db import DATA_DIR
from repositories import ppt_repository
from services.auth_service import require_login

PAGE_ANIMATION_DIR = DATA_DIR / "page_animation_states"
MAX_ANIMATION_STATES_PER_SLIDE = 30
AnimationCaptureFunc = Callable[[Path, Path], list[dict]]


@dataclass(frozen=True)
class AnimationGenerationResult:
    generated_by_slide: dict[int, int]
    skipped_reason: str = ""


def generate_deck_animation_states(
    deck: dict,
    slides: list[dict],
    *,
    capture_func: AnimationCaptureFunc | None = None,
    user=None,
    max_states_per_slide: int = MAX_ANIMATION_STATES_PER_SLIDE,
) -> AnimationGenerationResult:
    source_path = Path(str(deck.get("file_path") or ""))
    if source_path.suffix.lower() != ".pptx":
        return AnimationGenerationResult({}, "动画状态缓存仅支持 PPTX 文件。")
    if not source_path.exists() or not source_path.is_file():
        return AnimationGenerationResult({}, "找不到原始 PPTX 文件，无法生成动画状态。")
    if capture_func is None and platform.system() != "Windows":
        return AnimationGenerationResult({}, "当前环境不是 Windows，本版本不生成 PPTX 动画状态。")

    user = user or require_login()
    user_id = int(user.id)
    deck_id = int(deck["id"])
    slide_by_number = {int(slide["slide_number"]): slide for slide in slides}
    if not slide_by_number:
        return AnimationGenerationResult({}, "当前资料没有可用页面。")

    output_root = PAGE_ANIMATION_DIR / f"user_{user_id}" / f"deck_{deck_id}"
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root = output_root.with_name(f".{output_root.name}.{uuid.uuid4().hex}.tmp")
    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    capture = capture_func or _capture_pptx_animation_manifest
    try:
        raw_states = capture(source_path, temp_root)
    except Exception as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        return AnimationGenerationResult({}, str(exc))

    grouped = _group_states_by_slide(raw_states)
    selected_relative_paths: set[str] = set()
    states_by_slide_number: dict[int, list[dict]] = {}
    for slide_number, states in grouped.items():
        if slide_number not in slide_by_number:
            continue
        sampled = sample_animation_states(states, max_states=max_states_per_slide)
        if sampled:
            states_by_slide_number[slide_number] = sampled
            selected_relative_paths.update(str(item["relative_path"]) for item in sampled)

    if not states_by_slide_number:
        shutil.rmtree(temp_root, ignore_errors=True)
        return AnimationGenerationResult({}, "没有捕获到可用动画状态。")

    _remove_unselected_temp_images(temp_root, selected_relative_paths)
    if output_root.exists():
        shutil.rmtree(output_root)
    temp_root.replace(output_root)

    generated: dict[int, int] = {}
    for slide_number, states in states_by_slide_number.items():
        slide = slide_by_number[slide_number]
        db_states = [_state_for_db(state, output_root) for state in states]
        count = ppt_repository.replace_slide_animation_states(
            user_id,
            deck_id,
            int(slide["id"]),
            slide_number,
            db_states,
        )
        generated[slide_number] = count
    return AnimationGenerationResult(generated)


def sample_animation_states(states: list[dict], *, max_states: int = MAX_ANIMATION_STATES_PER_SLIDE) -> list[dict]:
    ordered = sorted(states, key=lambda item: int(item.get("state_index") or 0))
    max_count = max(1, int(max_states))
    if len(ordered) <= max_count:
        return [dict(item, sampled=False) for item in ordered]
    selected_positions = {
        round(index * (len(ordered) - 1) / (max_count - 1))
        for index in range(max_count)
    }
    cursor = 0
    while len(selected_positions) < max_count and cursor < len(ordered):
        selected_positions.add(cursor)
        cursor += 1
    return [dict(ordered[index], sampled=True) for index in sorted(selected_positions)[:max_count]]


def _group_states_by_slide(states: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for state in states:
        try:
            slide_number = int(state.get("slide_number") or 0)
            state_index = int(state.get("state_index") or 0)
        except (TypeError, ValueError):
            continue
        relative_path = str(state.get("relative_path") or "").strip()
        if slide_number <= 0 or state_index < 0 or not relative_path:
            continue
        grouped.setdefault(slide_number, []).append(
            {
                "slide_number": slide_number,
                "state_index": state_index,
                "relative_path": relative_path.replace("\\", "/"),
                "label": str(state.get("label") or _default_state_label(state_index)),
                "step_summary": str(state.get("step_summary") or _default_step_summary(state_index)),
            }
        )
    return grouped


def _state_for_db(state: dict, output_root: Path) -> dict:
    state_index = int(state.get("state_index") or 0)
    sampled = bool(state.get("sampled"))
    label = str(state.get("label") or _default_state_label(state_index))
    if sampled and "抽样" not in label:
        label = f"{label}（已抽样）"
    return {
        "state_index": state_index,
        "label": label,
        "image_path": str((output_root / str(state["relative_path"])).resolve()),
        "step_summary": str(state.get("step_summary") or _default_step_summary(state_index)),
    }


def _default_state_label(state_index: int) -> str:
    return "初始" if int(state_index) == 0 else f"第 {int(state_index)} 步"


def _default_step_summary(state_index: int) -> str:
    return "初始状态" if int(state_index) == 0 else f"第 {int(state_index)} 次点击后的状态"


def _remove_unselected_temp_images(temp_root: Path, selected_relative_paths: set[str]) -> None:
    selected = {path.replace("\\", "/") for path in selected_relative_paths}
    for image in temp_root.rglob("*.png"):
        relative = image.relative_to(temp_root).as_posix()
        if relative not in selected:
            image.unlink(missing_ok=True)


def _capture_pptx_animation_manifest(path: Path, target_dir: Path) -> list[dict]:
    manifest_path = target_dir / "manifest.json"
    script = _powerpoint_capture_script(path.resolve(), target_dir.resolve(), manifest_path.resolve())
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"PowerPoint 动画状态捕获失败：{completed.stderr or completed.stdout}")
    if not manifest_path.exists():
        raise RuntimeError("PowerPoint 动画状态捕获完成，但没有生成 manifest。")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("PowerPoint 动画状态 manifest 解析失败。") from exc
    if not isinstance(data, list):
        raise RuntimeError("PowerPoint 动画状态 manifest 格式不正确。")
    return data


def _powerpoint_capture_script(ppt_path: Path, out_dir: Path, manifest_path: Path) -> str:
    return f"""
$ErrorActionPreference = 'Stop'
$pptPath = {str(ppt_path)!r}
$outDir = {str(out_dir)!r}
$manifestPath = {str(manifest_path)!r}
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public struct RECT {{ public int Left; public int Top; public int Right; public int Bottom; }}
public static class Win32Capture {{
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
}}
"@
function Save-WindowPng($hwnd, $path) {{
    $rect = New-Object RECT
    [Win32Capture]::GetWindowRect([IntPtr]$hwnd, [ref]$rect) | Out-Null
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {{
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    }} finally {{
        $graphics.Dispose()
        $bitmap.Dispose()
    }}
}}
$app = New-Object -ComObject PowerPoint.Application
$manifest = New-Object System.Collections.Generic.List[object]
try {{
    $presentation = $app.Presentations.Open($pptPath, $false, $false, $false)
    try {{
        $presentation.SlideShowSettings.ShowType = 2
        $window = $presentation.SlideShowSettings.Run()
        Start-Sleep -Milliseconds 700
        try {{
            for ($slideIndex = 1; $slideIndex -le $presentation.Slides.Count; $slideIndex++) {{
                $view = $window.View
                $view.GotoSlide($slideIndex, 1)
                Start-Sleep -Milliseconds 250
                $clickCount = [int]$view.GetClickCount()
                for ($click = 0; $click -le $clickCount; $click++) {{
                    if ($click -gt 0) {{
                        $view.GotoClick($click)
                        Start-Sleep -Milliseconds 250
                    }}
                    $slideDirName = "slide_" + $slideIndex.ToString("000")
                    $slideDir = Join-Path $outDir $slideDirName
                    New-Item -ItemType Directory -Force -Path $slideDir | Out-Null
                    $fileName = "state_" + $click.ToString("000") + ".png"
                    $target = Join-Path $slideDir $fileName
                    Save-WindowPng $window.HWND $target
                    $relativePath = "$slideDirName/$fileName"
                    $label = if ($click -eq 0) {{ "初始" }} else {{ "第 $click 步" }}
                    $summary = if ($click -eq 0) {{ "初始状态" }} else {{ "第 $click 次点击后的状态" }}
                    $manifest.Add([PSCustomObject]@{{
                        slide_number = $slideIndex
                        state_index = $click
                        relative_path = $relativePath
                        label = $label
                        step_summary = $summary
                    }}) | Out-Null
                }}
            }}
        }} finally {{
            $window.View.Exit()
        }}
    }} finally {{
        $presentation.Close()
    }}
}} finally {{
    $app.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
}}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $manifestPath
"""
