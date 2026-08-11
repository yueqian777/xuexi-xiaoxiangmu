from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import StrictInt

from services import slide_explanation_write_service
from study_mcp.models import SlideExplanationInput, explanation_items_payload
from study_mcp.tool_runtime import APPEND_TOOL_ANNOTATIONS, ToolRuntime


MCP_MAX_EXPLANATION_BATCH = 25


def register_explanation_write_tools(server: MCPServer, runtime: ToolRuntime) -> None:
    @server.tool(
        description=(
            "Append a new explanation version to an existing user-owned slide. This modifies "
            "local study data. `slide_id`, `slide_number`, and `explanation` are required; "
            "`source_context` is optional provenance context, `deck_id` can assert the deck, and "
            "`expected_deck_fingerprint` rejects stale content. It never overwrites previous versions."
        ),
        annotations=APPEND_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_save_slide_explanation(
        ctx: Context,
        slide_id: StrictInt,
        slide_number: StrictInt,
        explanation: str,
        source_context: str | None = None,
        deck_id: StrictInt | None = None,
        expected_deck_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_save_slide_explanation",
            operation_type="WRITE",
            permission_keys=("write_slide_explanation",),
            target_type="slide",
            target_id=slide_id,
            action=lambda: {
                "result": slide_explanation_write_service.append_slide_explanation(
                    runtime.user_id,
                    slide_id,
                    slide_number,
                    explanation,
                    model="ChatGPT MCP",
                    deck_id=deck_id,
                    expected_deck_fingerprint=expected_deck_fingerprint,
                    source_context=source_context,
                )
            },
            success_summary="explanations_appended=1",
        )

    @server.tool(
        description=(
            "Atomically append explanation versions for up to 25 slides in one user-owned deck. "
            "`deck_id` identifies the deck, `slides` contains ID/number/explanation objects, and "
            "optional `expected_deck_fingerprint` rejects stale content. This modifies local study "
            "data, rolls back the whole batch on any error, and never overwrites previous versions."
        ),
        annotations=APPEND_TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def study_save_slide_explanations(
        ctx: Context,
        deck_id: StrictInt,
        slides: list[SlideExplanationInput],
        expected_deck_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        return runtime.execute(
            ctx,
            tool_name="study_save_slide_explanations",
            operation_type="WRITE",
            permission_keys=("write_slide_explanation",),
            target_type="deck",
            target_id=deck_id,
            action=lambda: {
                "result": slide_explanation_write_service.append_slide_explanations(
                    runtime.user_id,
                    explanation_items_payload(slides),
                    model="ChatGPT MCP",
                    deck_id=deck_id,
                    expected_deck_fingerprint=expected_deck_fingerprint,
                    max_items=MCP_MAX_EXPLANATION_BATCH,
                )
            },
            success_summary=f"batch_requested={len(slides)}",
        )
