from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import StrictInt

from services import study_mcp_domain_service as domain
from study_mcp.tool_runtime import READ_TOOL_ANNOTATIONS, ToolRuntime


def register_ppt_tools(server: MCPServer, runtime: ToolRuntime) -> None:
    @server.tool(
        description=(
            "Read the active PPT slide, its structure and latest explanation. Read-only. "
            "Set `include_neighbor_context` to include nearby pages and `neighbor_radius` "
            "to 0-2; neighboring context is bounded to at most two slides on each side."
        ),
        annotations=READ_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_get_current_slide(
        ctx: Context,
        include_neighbor_context: bool = False,
        neighbor_radius: StrictInt = 1,
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_get_current_slide",
            operation_type="READ",
            permission_keys=("read_current_context", "read_ppt"),
            target_type="slide",
            action=lambda: {
                "slide": domain.get_current_slide(
                    runtime.user_id,
                    include_neighbor_context=include_neighbor_context,
                    neighbor_radius=neighbor_radius,
                )
            },
            success_summary="slide=current",
        )

    @server.tool(
        description=(
            "Read a numbered range from one user-owned PPT deck. Read-only. "
            "`deck_id` identifies the owned deck; `start_slide` and `end_slide` are inclusive "
            "page numbers. The range is limited to 25 slides and cannot cross users."
        ),
        annotations=READ_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_read_slide_range(
        ctx: Context,
        deck_id: StrictInt,
        start_slide: StrictInt,
        end_slide: StrictInt,
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_read_slide_range",
            operation_type="READ",
            permission_keys=("read_ppt",),
            target_type="deck",
            target_id=deck_id,
            action=lambda: domain.read_slide_range(
                runtime.user_id, deck_id, start_slide, end_slide
            ),
            success_summary=f"range={start_slide}-{end_slide}",
        )
