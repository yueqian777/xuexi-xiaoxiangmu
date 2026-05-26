from __future__ import annotations

import json
import time
from typing import Any

LAST_READER_POSITION_SETTING_KEY = "ppt_reader_last_position"
LAST_READER_DECK_STATE_KEY = "ppt_reader_deck_id"
READER_ACTIVE_SLIDE_STATE_PREFIX = "ppt_reader_active_slide_"


def parse_reader_position(raw_value: str | None) -> dict[str, int]:
    try:
        data = json.loads(raw_value or "")
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}

    position: dict[str, int] = {}
    for key in ("deck_id", "slide_number"):
        try:
            value = int(data.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            position[key] = value
    return position


def reader_position_setting_key(user_id: int) -> str:
    return f"user:{int(user_id)}:{LAST_READER_POSITION_SETTING_KEY}"


def build_reader_position_payload(
    deck_id: int,
    slide_number: int | None = None,
    *,
    existing: dict[str, int] | None = None,
) -> dict[str, int]:
    try:
        deck_id = int(deck_id)
    except (TypeError, ValueError):
        return {}
    if deck_id <= 0:
        return {}

    existing = existing or {}
    if slide_number is None and existing.get("deck_id") == deck_id:
        slide_number = existing.get("slide_number")

    payload = {"deck_id": deck_id}
    try:
        slide_number_value = int(slide_number or 0)
    except (TypeError, ValueError):
        slide_number_value = 0
    if slide_number_value > 0:
        payload["slide_number"] = slide_number_value
    return payload


def default_reader_deck_id(
    deck_ids: list[int],
    last_position: dict[str, int],
    state_deck_id: Any = None,
) -> int:
    if not deck_ids:
        return 0

    remembered_deck_id = int(last_position.get("deck_id") or 0)
    if remembered_deck_id in deck_ids:
        return remembered_deck_id

    try:
        state_deck_id = int(state_deck_id or 0)
    except (TypeError, ValueError):
        state_deck_id = 0
    if state_deck_id in deck_ids:
        return state_deck_id

    return deck_ids[0]


def initial_reader_slide_number(deck_id: int, slides: list[dict], last_position: dict[str, int]) -> int:
    if not slides:
        return 1
    slide_numbers = {int(slide["slide_number"]) for slide in slides}
    remembered_slide = int(last_position.get("slide_number") or 0)
    if int(last_position.get("deck_id") or 0) == int(deck_id) and remembered_slide in slide_numbers:
        return remembered_slide
    return int(slides[0]["slide_number"])


def reader_active_slide_state_key(deck_id: int) -> str:
    return f"{READER_ACTIVE_SLIDE_STATE_PREFIX}{int(deck_id)}"


def reader_active_slide_number(
    deck_id: int,
    slides: list[dict],
    initial_slide_number: int,
    state: dict[str, Any],
) -> int:
    slide_numbers = {int(slide["slide_number"]) for slide in slides}
    if not slide_numbers:
        return 1
    try:
        active = int(state.get(reader_active_slide_state_key(deck_id)) or initial_slide_number)
    except (TypeError, ValueError):
        active = int(initial_slide_number)
    return active if active in slide_numbers else int(initial_slide_number)


def reader_image_window_slide_numbers(
    slides: list[dict],
    active_slide_number: int,
    *,
    radius: int,
) -> set[int]:
    if not slides:
        return set()
    ordered = [int(slide["slide_number"]) for slide in slides]
    try:
        active_index = ordered.index(int(active_slide_number))
    except ValueError:
        active_index = 0
    start = max(0, active_index - radius)
    end = min(len(ordered), active_index + radius + 1)
    return set(ordered[start:end])


def update_reader_position_state(
    state: dict[str, Any],
    *,
    deck_id: int,
    slide_number: int,
    token: str = "",
) -> bool:
    deck_id = int(deck_id)
    last_position_token_key = f"ppt_reader_position_last_token_{deck_id}"
    if token and state.get(last_position_token_key) == token:
        return False

    state_key = reader_active_slide_state_key(deck_id)
    try:
        previous_slide_number = int(state.get(state_key) or 0)
    except (TypeError, ValueError):
        previous_slide_number = 0

    state[state_key] = int(slide_number)
    if token:
        state[last_position_token_key] = token

    return previous_slide_number != int(slide_number)


def should_refresh_task(
    state: dict[str, Any],
    task: dict,
    state_key: str,
    *,
    interval: float,
    now: float | None = None,
) -> bool:
    task_key = (
        int(task.get("deck_id") or 0),
        int(task.get("processed") or 0),
        int(task.get("generated") or 0),
        int(task.get("skipped") or 0),
        int(task.get("failed") or 0),
        int(task.get("sections") or 0),
        str(task.get("status_text") or ""),
    )
    last_refresh = state.get(state_key) or {}
    now = time.monotonic() if now is None else now
    if last_refresh.get("task_key") == task_key and now - float(last_refresh.get("time") or 0) < interval:
        return False
    state[state_key] = {"task_key": task_key, "time": now}
    return True
