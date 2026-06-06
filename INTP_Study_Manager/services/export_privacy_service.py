from __future__ import annotations

from pathlib import Path


FORBIDDEN_PUBLIC_TERMS = [
    "slide_questions",
    "branch_questions",
    "knowledge_cards",
    "knowledge_links",
    "mistakes",
    "review_tasks",
    "study_sessions",
    "daily_review_logs",
    "daily_ai_review_plans",
    "parking_lot",
    "app_settings",
    "api_providers",
    "api_keys",
    "api_keys_user_",
    "API Key",
    "插问",
    "错因",
    "掌握度",
    "复习任务",
    "个人学习记录",
]


def assert_public_markdown_safe(text: str) -> None:
    for term in FORBIDDEN_PUBLIC_TERMS:
        if term in text:
            raise ValueError(f"public export contains private term: {term}")


def assert_public_package_files_safe(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file() and (path.name.endswith(".enc.json") or path.name.startswith("api_keys")):
            raise ValueError(f"public export contains sensitive file: {path.name}")
