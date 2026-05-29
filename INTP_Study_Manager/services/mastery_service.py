from __future__ import annotations


def clamp_mastery(value: int) -> int:
    return max(0, min(100, int(value)))


REVIEW_RESULT_PROFILES = {
    "完全掌握": {
        "quality": 5,
        "target": 110,
        "rate": 0.18,
        "evidence": "闭卷可完整解释，并能迁移到新题或反例。",
    },
    "基本掌握": {
        "quality": 4,
        "target": 80,
        "rate": 0.20,
        "evidence": "闭卷能说清主干，但推导细节或边界条件仍需巩固。",
    },
    "仍然模糊": {
        "quality": 2,
        "target": 35,
        "rate": 0.28,
        "evidence": "能认出概念，但回忆不完整或卡在关键步骤。",
    },
    "完全不会": {
        "quality": 0,
        "target": 0,
        "rate": 0.25,
        "evidence": "闭卷无法启动回答，需要回到定义、公式条件和例题。",
    },
}


def review_result_profile(result: str) -> dict[str, int | float | str] | None:
    return REVIEW_RESULT_PROFILES.get(str(result or "").strip())


def apply_review_result(current_mastery: int, result: str) -> int:
    current = clamp_mastery(current_mastery)
    profile = review_result_profile(result)
    if not profile:
        return current
    if int(profile["quality"]) == 0 and current <= 5:
        return 0

    target = int(profile["target"])
    rate = float(profile["rate"])
    updated = current + round((target - current) * rate)
    return clamp_mastery(updated)
