from __future__ import annotations

ERROR_CAUSE_CATEGORIES = [
    "概念不清",
    "公式记错",
    "条件漏看",
    "计算失误",
    "题型没识别",
    "思路方向错",
    "表达不严谨",
    "前置知识缺失",
]

REVIEW_INTERVALS = [
    (1, "第 1 天复习"),
    (3, "第 3 天复习"),
    (7, "第 7 天复习"),
    (14, "第 14 天复习"),
]

REVIEW_RESULTS = [
    "完全掌握",
    "基本掌握",
    "仍然模糊",
    "完全不会",
]

MASTERY_FORWARD_THRESHOLD = 70

