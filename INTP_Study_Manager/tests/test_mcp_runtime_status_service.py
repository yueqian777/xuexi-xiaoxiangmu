import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import mcp_runtime_status_service as runtime_status


class McpRuntimeStatusServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        data_dir = Path(self.tmp.name)
        self.db_path = data_dir / "study_manager.db"
        patchers = [
            patch.object(db, "DATA_DIR", data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()

    def test_started_runtime_is_user_scoped_and_reports_live_pid(self):
        with (
            patch.object(runtime_status, "_is_pid_running", return_value=True),
            patch.object(
                runtime_status, "_process_identity", return_value="process-start:4321"
            ),
        ):
            started = runtime_status.mark_runtime_started(7, pid=4321, transport="stdio")

        self.assertTrue(started["running"])
        self.assertEqual(started["state"], "running")
        self.assertEqual(started["pid"], 4321)
        self.assertEqual(started["transport"], "stdio")
        self.assertEqual(runtime_status.get_runtime_status(8)["state"], "never_started")

        row = db.fetch_one(
            "SELECT user_id, value FROM app_settings WHERE key = ?",
            (runtime_status.runtime_status_setting_key(7),),
        )
        payload = json.loads(row["value"])
        self.assertEqual(row["user_id"], 7)
        self.assertEqual(
            set(payload),
            {
                "pid",
                "transport",
                "started_at",
                "stopped_at",
                "runtime_version",
                "process_identity",
            },
        )
        self.assertEqual(payload["process_identity"], "process-start:4321")
        self.assertNotIn("token", row["value"].lower())
        self.assertNotIn("command", row["value"].lower())

    def test_dead_pid_is_reported_as_stale_not_running(self):
        with patch.object(runtime_status, "_is_pid_running", return_value=True):
            runtime_status.mark_runtime_started(3, pid=333, transport="stdio")

        with patch.object(runtime_status, "_is_pid_running", return_value=False):
            status = runtime_status.get_runtime_status(3)

        self.assertFalse(status["running"])
        self.assertEqual(status["state"], "stale")

    def test_stopped_runtime_remains_stopped_even_if_pid_is_reused(self):
        with patch.object(runtime_status, "_is_pid_running", return_value=True):
            runtime_status.mark_runtime_started(1, pid=101, transport="stdio")
            stopped = runtime_status.mark_runtime_stopped(1, pid=101)

        self.assertFalse(stopped["running"])
        self.assertEqual(stopped["state"], "stopped")
        self.assertTrue(stopped["stopped_at"])

        with patch.object(runtime_status, "_is_pid_running", return_value=True):
            self.assertEqual(runtime_status.get_runtime_status(1)["state"], "stopped")

    def test_reused_pid_with_different_process_identity_is_stale(self):
        with (
            patch.object(runtime_status, "_is_pid_running", return_value=True),
            patch.object(runtime_status, "_process_identity", return_value="process-a"),
        ):
            runtime_status.mark_runtime_started(1, pid=101, transport="stdio")

        with (
            patch.object(runtime_status, "_is_pid_running", return_value=True),
            patch.object(runtime_status, "_process_identity", return_value="process-b"),
        ):
            status = runtime_status.get_runtime_status(1)

        self.assertFalse(status["running"])
        self.assertEqual(status["state"], "stale")
        self.assertFalse(status["identity_verified"])

    def test_old_process_stop_is_a_noop_after_a_new_process_replaces_it(self):
        identities = {101: "process-old", 202: "process-new"}
        with (
            patch.object(runtime_status, "_is_pid_running", return_value=True),
            patch.object(
                runtime_status,
                "_process_identity",
                side_effect=lambda pid: identities[pid],
            ),
        ):
            runtime_status.mark_runtime_started(1, pid=101, transport="stdio")
            current = runtime_status.mark_runtime_started(1, pid=202, transport="stdio")
            stale_stop_result = runtime_status.mark_runtime_stopped(1, pid=101)

        self.assertEqual(stale_stop_result, current)
        self.assertTrue(stale_stop_result["running"])
        self.assertEqual(stale_stop_result["pid"], 202)
        self.assertIsNone(stale_stop_result["stopped_at"])

        row = db.fetch_one(
            "SELECT value FROM app_settings WHERE key = ? AND user_id = ?",
            (runtime_status.runtime_status_setting_key(1), 1),
        )
        payload = json.loads(row["value"])
        self.assertEqual(payload["pid"], 202)
        self.assertEqual(payload["process_identity"], "process-new")
        self.assertIsNone(payload["stopped_at"])

    def test_only_stdio_and_positive_pid_are_accepted(self):
        for invalid_pid in (0, -1, True, "abc"):
            with self.subTest(pid=invalid_pid):
                with self.assertRaises(ValueError):
                    runtime_status.mark_runtime_started(1, pid=invalid_pid)

        with self.assertRaisesRegex(ValueError, "stdio"):
            runtime_status.mark_runtime_started(1, pid=10, transport="http")

    def test_pid_probe_recognizes_the_current_process_without_modifying_it(self):
        self.assertTrue(runtime_status._is_pid_running(os.getpid()))
        self.assertTrue(runtime_status._process_identity(os.getpid()))

        status = runtime_status.mark_runtime_started(5)
        self.assertTrue(status["running"])
        self.assertTrue(status["identity_verified"])


if __name__ == "__main__":
    unittest.main()
