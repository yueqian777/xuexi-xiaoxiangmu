from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    """Launch Study MCP from a stable project root regardless of caller cwd."""

    project_root = str(PROJECT_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    os.chdir(PROJECT_ROOT)

    from study_mcp.server import main as server_main

    return server_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
