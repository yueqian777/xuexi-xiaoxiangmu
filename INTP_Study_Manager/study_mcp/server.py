from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from mcp.server import MCPServer

from services import mcp_runtime_status_service
from study_mcp import __version__
from study_mcp.context_tools import register_context_tools
from study_mcp.knowledge_tools import register_knowledge_tools
from study_mcp.ppt_tools import register_ppt_tools
from study_mcp.question_tools import register_question_tools
from study_mcp.review_tools import register_review_tools
from study_mcp.tool_runtime import ToolRuntime
from study_mcp.write_tools import register_explanation_write_tools


def create_server(user_id: int) -> MCPServer:
    """Build an independent stdio MCP server bound to exactly one local user."""

    runtime = ToolRuntime(user_id)
    server = MCPServer(
        name="intp-study-manager",
        title="INTP Study Manager",
        description=(
            "User-scoped local read/write tools for active learning context, PPT study, "
            "questions, knowledge cards, reviews, and append-only explanations."
        ),
        instructions=(
            "Read current state before writes. Never infer resource IDs. All writes are "
            "subject to local permissions, ownership checks, and audit logging."
        ),
        version=__version__,
        log_level="WARNING",
    )
    register_context_tools(server, runtime)
    register_ppt_tools(server, runtime)
    register_question_tools(server, runtime)
    register_knowledge_tools(server, runtime)
    register_review_tools(server, runtime)
    register_explanation_write_tools(server, runtime)
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m study_mcp.server",
        description="Run the local INTP Study Manager MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio",),
        default="stdio",
        help="Local MCP transport (v1 supports stdio only).",
    )
    parser.add_argument(
        "--user-id",
        type=_nonnegative_user_id,
        required=True,
        help="Required local Study Manager user ID bound to every tool call.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = create_server(args.user_id)
    mcp_runtime_status_service.mark_runtime_started(
        args.user_id, transport=args.transport
    )
    try:
        server.run(transport=args.transport)
    finally:
        mcp_runtime_status_service.mark_runtime_stopped(args.user_id)
    return 0


def _nonnegative_user_id(value: str) -> int:
    try:
        user_id = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("user_id 必须是非负整数") from exc
    if user_id < 0:
        raise argparse.ArgumentTypeError("user_id 必须是非负整数")
    return user_id


if __name__ == "__main__":
    raise SystemExit(main())
