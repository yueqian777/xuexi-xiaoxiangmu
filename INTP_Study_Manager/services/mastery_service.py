from __future__ import annotations


def clamp_mastery(value: int) -> int:
    return max(0, min(100, int(value)))


def apply_review_result(current_mastery: int, result: str) -> int:
    changes = {
        "完全掌握": 15,
        "基本掌握": 5,
        "仍然模糊": -5,
        "完全不会": -15,
    }
    return clamp_mastery(current_mastery + changes.get(result, 0))

