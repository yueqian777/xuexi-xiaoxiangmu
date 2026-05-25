from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from db import execute, fetch_all, fetch_one, insert_and_get_id
from models import ERROR_CAUSE_CATEGORIES, REVIEW_RESULTS
from services.ai_service import generate_text
from services.auth_service import require_login
from services.mastery_service import apply_review_result, clamp_mastery
from services.prompt_service import render_template
from services.review_service import mark_review_result

MAX_DAILY_REVIEW_QUESTIONS = 6
DEFAULT_DAILY_REVIEW_QUESTIONS = 5


def get_today_ai_review_plan(*, user_id: int | None = None) -> dict[str, Any] | None:
    user_id = user_id if user_id is not None else require_login().id
    return fetch_one(
        "SELECT * FROM daily_ai_review_plans WHERE user_id = ? AND review_date = ?",
        (user_id, date.today().isoformat()),
    )


def collect_review_candidates(limit: int = MAX_DAILY_REVIEW_QUESTIONS, *, user_id: int | None = None) -> list[dict[str, Any]]:
    user_id = user_id if user_id is not None else require_login().id
    today = date.today().isoformat()
    rows = fetch_all(
        """
        SELECT *
        FROM (
            SELECT
                kc.id AS knowledge_id,
                kc.subject,
                kc.topic,
                kc.core_question,
                kc.one_sentence,
                kc.logic_or_formula,
                kc.application,
                kc.mastery,
                kc.need_review,
                kc.created_at,
                (
                    SELECT rt.id
                    FROM review_tasks rt
                    WHERE rt.knowledge_id = kc.id
                      AND rt.review_date <= ?
                      AND rt.status = '待复习'
                    ORDER BY rt.review_date ASC, rt.id ASC
                    LIMIT 1
                ) AS task_id,
                (
                    SELECT rt.review_stage
                    FROM review_tasks rt
                    WHERE rt.knowledge_id = kc.id
                      AND rt.review_date <= ?
                      AND rt.status = '待复习'
                    ORDER BY rt.review_date ASC, rt.id ASC
                    LIMIT 1
                ) AS review_stage,
                (
                    SELECT m.cause_category
                    FROM mistakes m
                    WHERE m.user_id = kc.user_id AND (m.knowledge_id = kc.id OR (m.subject = kc.subject AND m.topic = kc.topic))
                    ORDER BY m.created_at DESC, m.id DESC
                    LIMIT 1
                ) AS last_cause
            FROM knowledge_cards kc
            WHERE kc.user_id = ?
        )
        WHERE task_id IS NOT NULL OR mastery < 70 OR need_review = 1
        ORDER BY
            CASE WHEN task_id IS NOT NULL THEN 0 ELSE 1 END,
            mastery ASC,
            created_at DESC,
            knowledge_id DESC
        LIMIT ?
        """,
        (today, today, user_id, limit),
    )
    return [_candidate_for_prompt(row) for row in rows]


def generate_today_ai_review_plan(
    *,
    provider_key: str,
    api_key: str,
    model: str,
    max_output_tokens: int = 1800,
    user_id: int | None = None,
) -> dict[str, Any]:
    user_id = user_id if user_id is not None else require_login().id
    candidates = collect_review_candidates(user_id=user_id)
    if not candidates:
        raise ValueError("今天没有可生成自测题的知识点。请先创建知识卡片，或等待复习任务到期。")

    max_questions = min(DEFAULT_DAILY_REVIEW_QUESTIONS, MAX_DAILY_REVIEW_QUESTIONS, len(candidates))
    prompt = render_template(
        "daily_ai_review_plan.md",
        {
            "today": date.today().isoformat(),
            "max_questions": str(max_questions),
            "candidates_json": json.dumps(candidates, ensure_ascii=False, indent=2),
        },
    )
    raw = generate_text(
        prompt,
        provider_key=provider_key,
        api_key=api_key,
        model_override=model,
        max_output_tokens=max_output_tokens,
    )
    plan = _normalize_plan_payload(_load_json_payload(raw), candidates, max_questions)
    _save_today_plan(
        provider_key=provider_key,
        model=model,
        plan=plan,
        candidates=candidates,
        status="待回答",
        user_id=user_id,
    )
    stored = get_today_ai_review_plan(user_id=user_id)
    if not stored:
        raise RuntimeError("自测计划已生成，但读取失败。")
    return stored


def regenerate_today_ai_review_plan(
    *,
    provider_key: str,
    api_key: str,
    model: str,
    max_output_tokens: int = 1800,
    user_id: int | None = None,
) -> dict[str, Any]:
    user_id = user_id if user_id is not None else require_login().id
    execute("DELETE FROM daily_ai_review_plans WHERE user_id = ? AND review_date = ?", (user_id, date.today().isoformat()))
    return generate_today_ai_review_plan(
        provider_key=provider_key,
        api_key=api_key,
        model=model,
        max_output_tokens=max_output_tokens,
        user_id=user_id,
    )


def evaluate_today_ai_review(
    *,
    plan_row: dict[str, Any],
    answers: dict[str, str],
    provider_key: str,
    api_key: str,
    model: str,
    max_output_tokens: int = 2200,
) -> dict[str, Any]:
    plan = json.loads(plan_row["plan_json"])
    normalized_answers = {
        question_id: answer.strip()
        for question_id, answer in answers.items()
        if str(question_id).strip()
    }
    prompt = render_template(
        "daily_ai_review_grade.md",
        {
            "today": date.today().isoformat(),
            "plan_json": json.dumps(plan, ensure_ascii=False, indent=2),
            "answers_json": json.dumps(normalized_answers, ensure_ascii=False, indent=2),
        },
    )
    raw = generate_text(
        prompt,
        provider_key=provider_key,
        api_key=api_key,
        model_override=model,
        max_output_tokens=max_output_tokens,
    )
    evaluation = _normalize_evaluation_payload(_load_json_payload(raw), plan, normalized_answers)
    updates = _apply_evaluation_results(plan, evaluation)
    evaluation["mastery_updates"] = updates
    execute(
        """
        UPDATE daily_ai_review_plans
        SET answers_json = ?,
            evaluation_json = ?,
            status = '已批改',
            evaluated_at = datetime('now', 'localtime')
        WHERE id = ? AND user_id = ?
        """,
        (
            json.dumps(normalized_answers, ensure_ascii=False),
            json.dumps(evaluation, ensure_ascii=False),
            plan_row["id"],
            plan_row.get("user_id", require_login().id),
        ),
    )
    return evaluation


def plan_payload(plan_row: dict[str, Any]) -> dict[str, Any]:
    return json.loads(plan_row.get("plan_json") or "{}")


def evaluation_payload(plan_row: dict[str, Any]) -> dict[str, Any] | None:
    text = plan_row.get("evaluation_json") or ""
    if not text.strip():
        return None
    return json.loads(text)


def answers_payload(plan_row: dict[str, Any]) -> dict[str, str]:
    text = plan_row.get("answers_json") or "{}"
    data = json.loads(text)
    return {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}


def _save_today_plan(
    *,
    user_id: int,
    provider_key: str,
    model: str,
    plan: dict[str, Any],
    candidates: list[dict[str, Any]],
    status: str,
) -> None:
    execute(
        """
        INSERT INTO daily_ai_review_plans (
            user_id, review_date, provider_key, model, plan_json, source_snapshot_json, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, review_date) DO UPDATE SET
            provider_key = excluded.provider_key,
            model = excluded.model,
            plan_json = excluded.plan_json,
            source_snapshot_json = excluded.source_snapshot_json,
            answers_json = '{}',
            evaluation_json = '',
            status = excluded.status,
            created_at = datetime('now', 'localtime'),
            evaluated_at = ''
        """,
        (
            user_id,
            date.today().isoformat(),
            provider_key,
            model,
            json.dumps(plan, ensure_ascii=False),
            json.dumps(candidates, ensure_ascii=False),
            status,
        ),
    )


def _candidate_for_prompt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "knowledge_id": int(row["knowledge_id"]),
        "task_id": int(row["task_id"]) if row.get("task_id") else None,
        "subject": row.get("subject") or "",
        "topic": row.get("topic") or "",
        "core_question": row.get("core_question") or "",
        "one_sentence": row.get("one_sentence") or "",
        "logic_or_formula": _clip(row.get("logic_or_formula") or "", 500),
        "application": _clip(row.get("application") or "", 400),
        "mastery": int(row.get("mastery") or 0),
        "review_stage": row.get("review_stage") or ("低掌握度重点复习" if int(row.get("mastery") or 0) < 70 else "常规复习"),
        "last_cause": row.get("last_cause") or "",
    }


def _normalize_plan_payload(
    payload: dict[str, Any],
    candidates: list[dict[str, Any]],
    max_questions: int,
) -> dict[str, Any]:
    candidate_ids = {int(item["knowledge_id"]) for item in candidates}
    raw_questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
    questions: list[dict[str, Any]] = []
    for index, item in enumerate(raw_questions, start=1):
        if not isinstance(item, dict):
            continue
        try:
            knowledge_id = int(item.get("knowledge_id"))
        except (TypeError, ValueError):
            continue
        if knowledge_id not in candidate_ids:
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        expected_points = item.get("expected_points")
        if not isinstance(expected_points, list):
            expected_points = []
        questions.append(
            {
                "question_id": str(item.get("question_id") or f"q{len(questions) + 1}"),
                "knowledge_id": knowledge_id,
                "topic": str(item.get("topic") or _topic_for_candidate(candidates, knowledge_id)),
                "question_type": str(item.get("question_type") or "概念解释题"),
                "question": question,
                "expected_points": [str(point).strip() for point in expected_points if str(point).strip()],
            }
        )
        if len(questions) >= max_questions:
            break

    if not questions:
        for index, candidate in enumerate(candidates[:max_questions], start=1):
            questions.append(
                {
                    "question_id": f"q{index}",
                    "knowledge_id": int(candidate["knowledge_id"]),
                    "topic": candidate["topic"],
                    "question_type": "概念解释题",
                    "question": f"闭卷解释：{candidate['topic']} 想解决什么核心问题？它和前面学过的哪些概念容易混淆？",
                    "expected_points": [candidate.get("core_question") or "说明核心问题", candidate.get("one_sentence") or "给出一句话解释"],
                }
            )

    return {
        "main_line": str(payload.get("main_line") or "今天用少量问题检查到期复习和低掌握度知识点。"),
        "questions": questions,
    }


def _normalize_evaluation_payload(
    payload: dict[str, Any],
    plan: dict[str, Any],
    answers: dict[str, str],
) -> dict[str, Any]:
    question_by_id = {item["question_id"]: item for item in plan.get("questions", [])}
    raw_evaluations = payload.get("evaluations") if isinstance(payload.get("evaluations"), list) else []
    evaluations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_evaluations:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or "").strip()
        if question_id not in question_by_id:
            continue
        seen.add(question_id)
        question = question_by_id[question_id]
        score = _clamp_int(item.get("score"), 0)
        result = _normalize_result(item.get("result"), score)
        evaluations.append(
            {
                "question_id": question_id,
                "knowledge_id": int(question["knowledge_id"]),
                "score": score,
                "result": result,
                "cause_category": _normalize_cause(item.get("cause_category")),
                "feedback": str(item.get("feedback") or "").strip(),
                "correct_answer": str(item.get("correct_answer") or "").strip(),
                "next_question": str(item.get("next_question") or "").strip(),
            }
        )

    for question_id, question in question_by_id.items():
        if question_id in seen:
            continue
        answer = answers.get(question_id, "").strip()
        score = 0 if not answer else 50
        evaluations.append(
            {
                "question_id": question_id,
                "knowledge_id": int(question["knowledge_id"]),
                "score": score,
                "result": _normalize_result(None, score),
                "cause_category": "概念不清" if answer else "前置知识缺失",
                "feedback": "未获得有效批改，已按回答完整度保守估计。",
                "correct_answer": "请重新生成或手动复盘本题。",
                "next_question": "这个知识点想解决什么核心问题？",
            }
        )

    return {
        "overall_summary": str(payload.get("overall_summary") or "已根据本次自测更新掌握度。"),
        "evaluations": evaluations,
    }


def _apply_evaluation_results(plan: dict[str, Any], evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    from services.auth_service import require_login

    user = require_login()
    plan_row = fetch_one(
        "SELECT source_snapshot_json FROM daily_ai_review_plans WHERE user_id = ? AND review_date = ?",
        (user.id, date.today().isoformat()),
    )
    source_items = json.loads((plan_row or {}).get("source_snapshot_json") or "[]")
    source_by_knowledge_id = {int(item["knowledge_id"]): item for item in source_items}
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in evaluation.get("evaluations", []):
        grouped.setdefault(int(item["knowledge_id"]), []).append(item)

    updates: list[dict[str, Any]] = []
    for knowledge_id, items in grouped.items():
        avg_score = round(sum(int(item["score"]) for item in items) / len(items))
        result = _normalize_result(None, avg_score)
        source = source_by_knowledge_id.get(knowledge_id, {})
        before_row = fetch_one("SELECT mastery FROM knowledge_cards WHERE id = ? AND user_id = ?", (knowledge_id, user.id))
        if not before_row:
            continue
        before = int(before_row["mastery"])
        task_id = source.get("task_id")
        if task_id:
            mark_review_result(int(task_id), result)
        else:
            after = apply_review_result(before, result)
            execute(
                "UPDATE knowledge_cards SET mastery = ?, need_review = ? WHERE id = ? AND user_id = ?",
                (after, int(after < 70 or result in {"仍然模糊", "完全不会"}), knowledge_id, user.id),
            )
            if result == "仍然模糊":
                _create_extra_review(knowledge_id, 2, "AI 追加复习：2 天后", user_id=user.id)
            elif result == "完全不会":
                _create_extra_review(knowledge_id, 1, "AI 重点突破：1 天后", user_id=user.id)
        after_row = fetch_one("SELECT mastery FROM knowledge_cards WHERE id = ? AND user_id = ?", (knowledge_id, user.id))
        after = int(after_row["mastery"]) if after_row else before
        updates.append(
            {
                "knowledge_id": knowledge_id,
                "topic": source.get("topic") or _topic_for_plan(plan, knowledge_id),
                "score": avg_score,
                "result": result,
                "mastery_before": before,
                "mastery_after": after,
            }
        )
    return updates


def _create_extra_review(knowledge_id: int, days: int, stage: str, *, user_id: int) -> None:
    insert_and_get_id(
        """
        INSERT INTO review_tasks (user_id, knowledge_id, review_date, review_stage)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, knowledge_id, (date.today() + timedelta(days=days)).isoformat(), stage),
    )


def _load_json_payload(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    if not (text.startswith("{") and text.endswith("}")):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("API 返回内容里没有可解析的 JSON。")
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text))
    if not isinstance(payload, dict):
        raise ValueError("API 返回内容不是 JSON 对象。")
    return payload


def _topic_for_candidate(candidates: list[dict[str, Any]], knowledge_id: int) -> str:
    for candidate in candidates:
        if int(candidate["knowledge_id"]) == knowledge_id:
            return str(candidate.get("topic") or "未命名知识点")
    return "未命名知识点"


def _topic_for_plan(plan: dict[str, Any], knowledge_id: int) -> str:
    for question in plan.get("questions", []):
        if int(question.get("knowledge_id") or 0) == knowledge_id:
            return str(question.get("topic") or "未命名知识点")
    return "未命名知识点"


def _normalize_result(value: Any, score: int) -> str:
    text = str(value or "").strip()
    if text in REVIEW_RESULTS:
        return text
    if score >= 85:
        return "完全掌握"
    if score >= 65:
        return "基本掌握"
    if score >= 40:
        return "仍然模糊"
    return "完全不会"


def _normalize_cause(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in ERROR_CAUSE_CATEGORIES else "概念不清"


def _clamp_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return clamp_mastery(number)


def _clip(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."
