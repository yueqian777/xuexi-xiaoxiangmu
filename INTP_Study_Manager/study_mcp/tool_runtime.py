from __future__ import annotations

import logging
import hashlib
from collections.abc import Callable, Iterable
from typing import Any

from mcp.types import ToolAnnotations

from services import mcp_audit_service, mcp_permission_service
from services.slide_explanation_write_service import SlideExplanationWriteError
from services.study_mcp_domain_service import StudyDomainError


LOGGER = logging.getLogger("study_mcp")

READ_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
APPEND_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
IDEMPOTENT_WRITE_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

_PERMISSION_MESSAGES = {
    "read_current_context": "本地未授权读取当前学习上下文。",
    "read_ppt": "本地未授权读取 PPT 内容。",
    "read_question_tree": "本地未授权读取插问树。",
    "read_knowledge_cards": "本地未授权读取知识卡片。",
    "read_reviews": "本地未授权读取复习记录。",
    "write_slide_explanation": "本地未授权新增逐页讲解。",
    "write_slide_question": "本地未授权新增或更新插问。",
    "write_knowledge_card": "本地未授权转换知识卡片。",
    "write_review": "本地未授权创建或更新复习任务。",
}


class ToolRuntime:
    """Apply local authorization, error mapping, and minimal audit metadata."""

    def __init__(self, user_id: int):
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 0:
            raise ValueError("user_id 必须是非负整数。")
        self.user_id = user_id

    def execute(
        self,
        context: Any,
        *,
        tool_name: str,
        operation_type: str,
        permission_keys: Iterable[str],
        target_type: str = "",
        target_id: str | int = "",
        action: Callable[[], dict[str, Any]],
        success_summary: str = "status=success",
    ) -> dict[str, Any]:
        request_id = self._request_id(context)
        permissions = tuple(permission_keys)
        for permission_key in permissions:
            try:
                allowed = mcp_permission_service.is_permission_allowed(
                    self.user_id, permission_key
                )
            except Exception:
                LOGGER.exception("MCP permission check failed for %s", tool_name)
                self._audit_best_effort(
                    request_id,
                    tool_name,
                    operation_type,
                    target_type,
                    target_id,
                    success=False,
                    permission_result="permission_denied",
                    summary="permission_check_failed",
                )
                return self._error(
                    "permission_check_failed", "本地权限状态无法读取，本次操作未执行。"
                )
            if not allowed:
                self._audit_best_effort(
                    request_id,
                    tool_name,
                    operation_type,
                    target_type,
                    target_id,
                    success=False,
                    permission_result="permission_denied",
                    summary=f"permission={permission_key}",
                )
                return self._error(
                    "permission_denied",
                    _PERMISSION_MESSAGES.get(permission_key, "本地未授权执行该操作。"),
                )

        try:
            audit_id = mcp_audit_service.record_audit_log(
                self.user_id,
                request_id,
                tool_name,
                operation_type,
                target_type,
                target_id,
                success=False,
                permission_result="allowed",
                summary="status=started",
            )
        except Exception:
            LOGGER.exception("Could not create MCP audit attempt for %s", tool_name)
            return self._error(
                "audit_unavailable",
                "本地审计日志当前不可用，本次操作未执行。",
            )

        try:
            payload = action()
            if not isinstance(payload, dict):
                raise TypeError("tool action must return a dict")
        except Exception as exc:
            code, message = self._safe_error(exc)
            if code == "internal_error":
                LOGGER.exception("Unhandled MCP tool error in %s", tool_name)
            self._finalize_best_effort(
                audit_id,
                success=False,
                permission_result="allowed",
                summary=f"error_code={code}",
            )
            return self._error(code, message)

        audit_finalized = self._finalize_best_effort(
            audit_id,
            success=True,
            permission_result="allowed",
            summary=success_summary,
        )
        response = {"ok": True, **payload}
        if not audit_finalized:
            response["warnings"] = [
                {
                    "code": "audit_finalize_failed",
                    "message": "操作已完成，但本地审计仅保留开始记录；请勿盲目重试写入。",
                }
            ]
        return response

    @staticmethod
    def _request_id(context: Any) -> str:
        value = getattr(context, "request_id", "")
        try:
            raw = str(value).encode("utf-8", errors="backslashreplace")
        except Exception:
            raw = b"unprintable-request-id"
        digest = hashlib.sha256(raw).hexdigest()
        return f"req-sha256-{digest}"

    @staticmethod
    def _safe_error(exc: Exception) -> tuple[str, str]:
        if isinstance(exc, (StudyDomainError, SlideExplanationWriteError)):
            code = exc.code
            message = exc.message
            return code[:80], message[:500]
        return "internal_error", "本地工具执行失败；详细信息已写入本地日志。"

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "error": {"code": code, "message": message}}

    def _audit_best_effort(
        self,
        request_id: str,
        tool_name: str,
        operation_type: str,
        target_type: str,
        target_id: str | int,
        *,
        success: bool,
        permission_result: str,
        summary: str,
    ) -> None:
        try:
            mcp_audit_service.record_audit_log(
                self.user_id,
                request_id,
                tool_name,
                operation_type,
                target_type,
                target_id,
                success=success,
                permission_result=permission_result,
                summary=summary,
            )
        except Exception:
            LOGGER.exception("Could not persist MCP audit metadata for %s", tool_name)

    def _finalize_best_effort(
        self,
        audit_id: int,
        *,
        success: bool,
        permission_result: str,
        summary: str,
    ) -> bool:
        try:
            updated = mcp_audit_service.finalize_audit_log(
                self.user_id,
                audit_id,
                success=success,
                permission_result=permission_result,
                summary=summary,
            )
            if not updated:
                LOGGER.error("MCP audit attempt disappeared before finalization: %s", audit_id)
            return bool(updated)
        except Exception:
            LOGGER.exception("Could not finalize MCP audit metadata: %s", audit_id)
            return False
