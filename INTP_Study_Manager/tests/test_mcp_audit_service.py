import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import mcp_audit_service as audit_service


class McpAuditServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.data_dir / "study_manager.db"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()

    def _record(self, user_id=7, **overrides):
        values = {
            "request_id": "request-123",
            "tool_name": "study_get_current_slide",
            "operation_type": "READ",
            "target_type": "slide",
            "target_id": "381",
            "success": True,
            "permission_result": "allowed",
            "summary": "slide_id=381 neighbor_count=0",
        }
        values.update(overrides)
        return audit_service.record_audit_log(user_id, **values)

    def test_record_audit_log_persists_the_minimum_structured_fields(self):
        audit_id = self._record()

        row = db.fetch_one("SELECT * FROM mcp_audit_logs WHERE id = ?", (audit_id,))
        self.assertEqual(row["user_id"], 7)
        self.assertEqual(row["request_id"], "request-123")
        self.assertEqual(row["tool_name"], "study_get_current_slide")
        self.assertEqual(row["operation_type"], "READ")
        self.assertEqual(row["target_type"], "slide")
        self.assertEqual(row["target_id"], "381")
        self.assertEqual(row["success"], 1)
        self.assertEqual(row["permission_result"], "allowed")
        self.assertEqual(row["summary"], "slide_id=381 neighbor_count=0")
        self.assertTrue(row["created_at"])

    def test_adapter_can_pass_identity_and_target_fields_positionally(self):
        audit_id = audit_service.record_audit_log(
            7,
            "request-positional",
            "study_get_current_context",
            "READ",
            "context",
            "active",
            success=True,
            permission_result="allowed",
            summary="context=active",
        )

        row = db.fetch_one(
            "SELECT request_id, target_id FROM mcp_audit_logs WHERE id = ?",
            (audit_id,),
        )
        self.assertEqual(
            row,
            {"request_id": "request-positional", "target_id": "active"},
        )

    def test_permission_denied_is_recorded_as_an_unsuccessful_attempt(self):
        audit_id = self._record(
            tool_name="study_get_today_reviews",
            target_type="review",
            target_id="",
            success=False,
            permission_result="permission_denied",
            summary="permission=read_reviews",
        )

        row = db.fetch_one(
            "SELECT success, permission_result FROM mcp_audit_logs WHERE id = ?",
            (audit_id,),
        )
        self.assertEqual(row, {"success": 0, "permission_result": "permission_denied"})

    def test_recent_logs_are_strictly_user_scoped(self):
        first = self._record(user_id=7, request_id="request-user-7")
        self._record(user_id=8, request_id="request-user-8")

        rows = audit_service.list_recent_audit_logs(7)

        self.assertEqual([row["id"] for row in rows], [first])
        self.assertEqual({row["user_id"] for row in rows}, {7})

    def test_recent_logs_limit_is_bounded(self):
        for index in range(3):
            self._record(request_id=f"request-{index}")

        self.assertEqual(len(audit_service.list_recent_audit_logs(7, 2)), 2)
        with self.assertRaisesRegex(ValueError, "limit"):
            audit_service.list_recent_audit_logs(7, limit=0)
        with self.assertRaisesRegex(ValueError, "limit"):
            audit_service.list_recent_audit_logs(
                7, limit=audit_service.MAX_RECENT_LOGS + 1
            )

    def test_summary_is_collapsed_and_limited_to_300_characters(self):
        audit_id = self._record(summary="slide_id=381\n\tstatus=ok")
        row = db.fetch_one(
            "SELECT summary FROM mcp_audit_logs WHERE id = ?", (audit_id,)
        )
        self.assertEqual(row["summary"], "slide_id=381 status=ok")

        with self.assertRaisesRegex(ValueError, "summary"):
            self._record(request_id="too-long", summary="x" * 301)
        self.assertIsNone(
            db.fetch_one(
                "SELECT id FROM mcp_audit_logs WHERE request_id = ?", ("too-long",)
            )
        )

    def test_audit_api_has_no_body_or_secret_parameters(self):
        parameters = inspect.signature(audit_service.record_audit_log).parameters
        for forbidden in ("explanation", "prompt", "content", "secret", "api_key"):
            self.assertNotIn(forbidden, parameters)

        with self.assertRaises(TypeError):
            self._record(explanation="完整逐页讲解正文")

    def test_audit_api_rejects_delete_operations(self):
        with self.assertRaisesRegex(ValueError, "operation_type"):
            self._record(operation_type="DELETE")

    def test_success_requires_a_real_boolean(self):
        for value in (1, 0, "true", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "success"):
                    self._record(success=value)

    def test_permission_result_is_an_explicit_allow_or_deny_value(self):
        for value in ("", "yes", "not_checked", "ALLOWED"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "permission_result"):
                    self._record(permission_result=value)

    def test_identifier_fields_reject_empty_control_or_oversized_values(self):
        invalid_cases = [
            ("request_id", ""),
            ("request_id", "x" * (audit_service.MAX_REQUEST_ID_CHARS + 1)),
            ("tool_name", "bad\ntool"),
            ("tool_name", "x" * (audit_service.MAX_TOOL_NAME_CHARS + 1)),
            ("target_type", "bad target"),
            ("target_id", "bad\x00id"),
        ]
        for field, value in invalid_cases:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self._record(**{field: value})

    def test_user_and_limit_reject_bool_or_non_integer_values(self):
        with self.assertRaisesRegex(ValueError, "user_id"):
            self._record(user_id=True)
        with self.assertRaisesRegex(ValueError, "limit"):
            audit_service.list_recent_audit_logs(7, limit=True)

    def test_finalize_updates_one_user_scoped_attempt_in_place(self):
        audit_id = self._record(
            success=False,
            permission_result="allowed",
            summary="status=started",
        )

        updated = audit_service.finalize_audit_log(
            7,
            audit_id,
            success=True,
            permission_result="allowed",
            summary="status=success",
        )

        self.assertTrue(updated)
        row = db.fetch_one(
            "SELECT success, summary FROM mcp_audit_logs WHERE id = ?", (audit_id,)
        )
        self.assertEqual(row, {"success": 1, "summary": "status=success"})
        self.assertFalse(
            audit_service.finalize_audit_log(
                8,
                audit_id,
                success=True,
                permission_result="allowed",
                summary="must-not-update",
            )
        )


if __name__ == "__main__":
    unittest.main()
