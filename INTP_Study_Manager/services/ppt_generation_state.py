from __future__ import annotations


def apply_stop_request(task: dict, *, default_status_text: str) -> str:
    status = task.get("status")
    if task.get("stop_requested") and status == "running":
        task["status"] = "stopped"
        task["status_text"] = task.get("status_text") or default_status_text
        return "stopped"
    return str(status or "")


def generation_progress_patch(
    *,
    processed: int,
    total: int,
    generated: int,
    skipped: int,
    failed: int,
    inflight: list[int],
    message: str = "",
) -> dict:
    patch = {
        "processed": int(processed),
        "generated": int(generated),
        "skipped": int(skipped),
        "failed": int(failed),
        "inflight_slide_numbers": list(inflight),
        "progress": (int(processed) / int(total)) if int(total or 0) else 1.0,
    }
    if message:
        patch["status_text"] = message
    elif inflight:
        pages = "、".join(str(number) for number in inflight[:4])
        suffix = "..." if len(inflight) > 4 else ""
        patch["status_text"] = f"正在并行分析第 {pages}{suffix} 页；已完成 {processed} / {total} 页。"
    else:
        patch["status_text"] = f"已完成 {processed} / {total} 页。"
    return patch
