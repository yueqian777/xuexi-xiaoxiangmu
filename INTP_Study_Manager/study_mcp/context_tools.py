from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from services import active_learning_context_service
from study_mcp.tool_runtime import READ_TOOL_ANNOTATIONS, ToolRuntime


def register_context_tools(server: MCPServer, runtime: ToolRuntime) -> None:
    @server.tool(
        description=(
            "Read the Study Manager user's current active learning context. "
            "This is read-only, returns active=false when no context exists, and never guesses state."
        ),
        annotations=READ_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_get_current_context(ctx: Context) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            current = active_learning_context_service.get_active_context(runtime.user_id)
            if not current.get("active"):
                return {"active": False}
            context_payload = dict(current)
            context_payload.pop("active", None)
            return {"active": True, "context": context_payload}

        return runtime.execute(
            ctx,
            tool_name="study_get_current_context",
            operation_type="READ",
            permission_keys=("read_current_context",),
            target_type="context",
            target_id="active",
            action=action,
            success_summary="context=queried",
        )

