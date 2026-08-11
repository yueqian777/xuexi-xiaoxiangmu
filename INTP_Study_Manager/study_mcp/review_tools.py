from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import StrictInt

from services import study_mcp_domain_service as domain
from study_mcp.tool_runtime import (
    IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
    READ_TOOL_ANNOTATIONS,
    ToolRuntime,
)


def register_review_tools(server: MCPServer, runtime: ToolRuntime) -> None:
    @server.tool(
        description=(
            "Read the current user's due and overdue review tasks for today with knowledge "
            "and mastery metadata. This is read-only."
        ),
        annotations=READ_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_get_today_reviews(ctx: Context) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            reviews = domain.get_today_reviews(runtime.user_id)
            return {"count": len(reviews), "reviews": reviews}

        return runtime.execute(
            ctx,
            tool_name="study_get_today_reviews",
            operation_type="READ",
            permission_keys=("read_reviews",),
            target_type="review",
            action=action,
            success_summary="reviews=today",
        )

    @server.tool(
        description=(
            "Submit one allowed result for a pending user-owned review task through the existing "
            "mastery service. `review_task_id` identifies the task and `result` must be one of the "
            "configured review-result labels. This modifies review/mastery data, is idempotent "
            "after completion, and never deletes data."
        ),
        annotations=IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_submit_review_result(
        ctx: Context, review_task_id: StrictInt, result: str
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_submit_review_result",
            operation_type="WRITE",
            permission_keys=("write_review",),
            target_type="review",
            target_id=review_task_id,
            action=lambda: {
                "result": domain.submit_review_result(
                    runtime.user_id, review_task_id, result
                )
            },
            success_summary="review=submitted",
        )
