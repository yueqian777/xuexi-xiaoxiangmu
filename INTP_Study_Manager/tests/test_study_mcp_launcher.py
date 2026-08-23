from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_ROOT / "scripts" / "run_study_mcp.py"


class StudyMcpLauncherTest(unittest.TestCase):
    def test_help_works_when_launched_outside_the_repository(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            completed = subprocess.run(
                [sys.executable, "-X", "utf8", str(LAUNCHER), "--help"],
                cwd=tmp,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Run the local INTP Study Manager MCP server", completed.stdout)
        self.assertIn("--user-id", completed.stdout)

    def test_launcher_preserves_server_argument_validation(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(LAUNCHER),
                    "--transport",
                    "stdio",
                    "--user-id",
                    "-1",
                ],
                cwd=tmp,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("user_id 必须是非负整数", completed.stderr)


if __name__ == "__main__":
    unittest.main()
