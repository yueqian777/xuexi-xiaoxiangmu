from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ISOLATED_SERVER_SCRIPT = """
import sys
from pathlib import Path
import db

db.DATA_DIR = Path(sys.argv[1])
db.DATABASE_PATH = db.DATA_DIR / "study_manager.db"
db._INITIALIZED_DATABASE_PATH = None

from study_mcp.server import main
raise SystemExit(main(["--transport", "stdio", "--user-id", "0"]))
"""


class StudyMcpStdioTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_process_initializes_lists_tools_and_calls_context(self):
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as data_dir,
            tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_log,
        ):
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-c", ISOLATED_SERVER_SCRIPT, data_dir],
                cwd=PROJECT_ROOT,
            )
            async with stdio_client(parameters, errlog=stderr_log) as streams:
                async with ClientSession(*streams) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    context = await session.call_tool(
                        "study_get_current_context", {}
                    )

            stderr_log.seek(0)
            stderr_text = stderr_log.read()

        self.assertEqual(initialized.server_info.name, "intp-study-manager")
        self.assertEqual(len(tools.tools), 14)
        self.assertEqual(context.structured_content, {"ok": True, "active": False})
        self.assertEqual(stderr_text, "")


if __name__ == "__main__":
    unittest.main()
