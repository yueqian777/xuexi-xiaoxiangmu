from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import StrictInt

from services import study_mcp_domain_service as domain
from study_mcp.tool_runtime import (
    APPEND_TOOL_ANNOTATIONS,
    IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
    READ_TOOL_ANNOTATIONS,
    ToolRuntime,
)


def register_question_tools(server: MCPServer, runtime: ToolRuntime) -> None:
    @server.tool(
        description=(
            "Read the complete root/child/grandchild question tree for one user-owned slide. "
            "`slide_id` identifies that slide. This is read-only and preserves parent, root, "
            "depth and status fields."
        ),
        annotations=READ_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_get_question_tree(ctx: Context, slide_id: StrictInt) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_get_question_tree",
            operation_type="READ",
            permission_keys=("read_question_tree",),
            target_type="slide",
            target_id=slide_id,
            action=lambda: domain.get_question_tree(runtime.user_id, slide_id),
            success_summary="question_tree=read",
        )

    @server.tool(
        description=(
            "Append a new root or child question to an existing user-owned slide. "
            "`slide_id`, `question`, and `answer` are required; `parent_question_id` creates a "
            "child and `quote_text` records a short source quote. This modifies local study "
            "data and never deletes an existing question."
        ),
        annotations=APPEND_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_add_slide_question(
        ctx: Context,
        slide_id: StrictInt,
        question: str,
        answer: str,
        parent_question_id: StrictInt | None = None,
        quote_text: str = "",
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_add_slide_question",
            operation_type="WRITE",
            permission_keys=("write_slide_question",),
            target_type="slide",
            target_id=slide_id,
            action=lambda: {
                "result": domain.add_slide_question(
                    runtime.user_id,
                    slide_id,
                    question,
                    answer,
                    parent_question_id=parent_question_id,
                    quote_text=quote_text,
                )
            },
            success_summary="question=created",
        )

    @server.tool(
        description=(
            "Convert a user-owned slide question into a knowledge card using the existing "
            "idempotent conversion workflow. `question_id` identifies the owned question. This "
            "modifies knowledge and review data; it never deletes."
        ),
        annotations=IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_convert_question_to_knowledge(
        ctx: Context, question_id: StrictInt
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_convert_question_to_knowledge",
            operation_type="WRITE",
            permission_keys=("write_knowledge_card", "write_review"),
            target_type="question",
            target_id=question_id,
            action=lambda: {
                "result": domain.convert_question_to_knowledge(
                    runtime.user_id, question_id
                )
            },
            success_summary="knowledge=ensured",
        )

    @server.tool(
        description=(
            "Mark a user-owned slide question as understood through the existing domain service. "
            "`question_id` identifies it. This modifies question status, is idempotent, and "
            "does not delete data."
        ),
        annotations=IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_mark_question_understood(
        ctx: Context, question_id: StrictInt
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_mark_question_understood",
            operation_type="WRITE",
            permission_keys=("write_slide_question",),
            target_type="question",
            target_id=question_id,
            action=lambda: {
                "result": domain.mark_question_understood(runtime.user_id, question_id)
            },
            success_summary="question=understood",
        )

    @server.tool(
        description=(
            "Ensure review tasks for a user-owned question via the existing conversion/review workflow. "
            "`question_id` identifies it. This modifies knowledge and review data, is idempotent, "
            "and never deletes data."
        ),
        annotations=IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_create_review_for_question(
        ctx: Context, question_id: StrictInt
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_create_review_for_question",
            operation_type="WRITE",
            permission_keys=("write_knowledge_card", "write_review"),
            target_type="question",
            target_id=question_id,
            action=lambda: {
                "result": domain.create_review_for_question(runtime.user_id, question_id)
            },
            success_summary="reviews=ensured",
        )
