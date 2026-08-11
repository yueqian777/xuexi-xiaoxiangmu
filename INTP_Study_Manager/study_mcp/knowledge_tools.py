from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import StrictInt

from services import study_mcp_domain_service as domain
from study_mcp.tool_runtime import READ_TOOL_ANNOTATIONS, ToolRuntime


def register_knowledge_tools(server: MCPServer, runtime: ToolRuntime) -> None:
    @server.tool(
        description=(
            "Read one user-owned knowledge card selected by `knowledge_id`. This is read-only and never returns "
            "another user's card."
        ),
        annotations=READ_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_get_knowledge_card(
        ctx: Context, knowledge_id: StrictInt
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_get_knowledge_card",
            operation_type="READ",
            permission_keys=("read_knowledge_cards",),
            target_type="knowledge",
            target_id=knowledge_id,
            action=lambda: {
                "knowledge": domain.get_knowledge_card(runtime.user_id, knowledge_id)
            },
            success_summary="knowledge=read",
        )

    @server.tool(
        description=(
            "Search the current user's knowledge cards using required `query`, optional `subject`, "
            "and bounded `limit` (maximum 50). This is read-only."
        ),
        annotations=READ_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_search_knowledge(
        ctx: Context,
        query: str,
        subject: str | None = None,
        limit: StrictInt = 10,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            items = domain.search_knowledge(
                runtime.user_id, query, subject=subject, limit=limit
            )
            return {"count": len(items), "results": items}

        return runtime.execute(
            ctx,
            tool_name="study_search_knowledge",
            operation_type="READ",
            permission_keys=("read_knowledge_cards",),
            target_type="knowledge",
            action=action,
            success_summary="knowledge=searched",
        )
