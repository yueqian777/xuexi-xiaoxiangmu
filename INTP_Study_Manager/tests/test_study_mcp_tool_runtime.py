from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import db
from study_mcp.tool_runtime import ToolRuntime


class StudyMcpToolRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        data_dir = Path(self.tmp.name)
        patchers = [
            patch.object(db, "DATA_DIR", data_dir),
            patch.object(db, "DATABASE_PATH", data_dir / "study_manager.db"),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()
        self.runtime = ToolRuntime(7)

    def _execute(self, request_id, action):
        return self.runtime.execute(
            SimpleNamespace(request_id=request_id),
            tool_name="study_save_slide_explanation",
            operation_type="WRITE",
            permission_keys=("write_slide_explanation",),
            target_type="slide",
            target_id=381,
            action=action,
            success_summary="explanations_appended=1",
        )

    def test_client_request_id_is_hashed_before_audit_and_cannot_inject_secret(self):
        result = self._execute("sk-test token with spaces", lambda: {"saved": True})

        self.assertTrue(result["ok"])
        row = db.fetch_one(
            "SELECT request_id, success, summary FROM mcp_audit_logs WHERE user_id = 7"
        )
        self.assertTrue(row["request_id"].startswith("req-sha256-"))
        self.assertNotIn("sk-test", row["request_id"])
        self.assertEqual(row["success"], 1)
        self.assertEqual(row["summary"], "explanations_appended=1")

    def test_allowed_action_fails_closed_when_attempt_audit_cannot_be_created(self):
        action = Mock(return_value={"saved": True})
        with patch(
            "study_mcp.tool_runtime.mcp_audit_service.record_audit_log",
            side_effect=sqlite3.OperationalError("database locked"),
        ):
            result = self._execute(-1, action)

        self.assertEqual(result["error"]["code"], "audit_unavailable")
        action.assert_not_called()

    def test_action_failure_finalizes_the_precreated_audit_without_body_content(self):
        secret = "complete explanation body must stay private"

        def fail():
            raise RuntimeError(secret)

        result = self._execute("request-failure", fail)

        self.assertEqual(result["error"]["code"], "internal_error")
        rows = db.fetch_all(
            "SELECT success, permission_result, summary FROM mcp_audit_logs WHERE user_id = 7"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["success"], 0)
        self.assertEqual(rows[0]["permission_result"], "allowed")
        self.assertEqual(rows[0]["summary"], "error_code=internal_error")
        self.assertNotIn(secret, repr(rows))

    def test_untrusted_value_error_message_is_not_returned_to_the_client(self):
        secret = "private path C:/secret/data"

        result = self._execute(
            "request-value-error",
            lambda: (_ for _ in ()).throw(ValueError(secret)),
        )

        self.assertEqual(result["error"]["code"], "internal_error")
        self.assertNotIn(secret, repr(result))

    def test_success_reports_warning_if_audit_attempt_cannot_be_finalized(self):
        with patch(
            "study_mcp.tool_runtime.mcp_audit_service.finalize_audit_log",
            side_effect=sqlite3.OperationalError("database locked"),
        ):
            result = self._execute("request-finalize", lambda: {"saved": True})

        self.assertTrue(result["ok"])
        self.assertEqual(result["warnings"][0]["code"], "audit_finalize_failed")
        row = db.fetch_one(
            "SELECT success, summary FROM mcp_audit_logs WHERE user_id = 7"
        )
        self.assertEqual(row, {"success": 0, "summary": "status=started"})


if __name__ == "__main__":
    unittest.main()
