import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class McpDatabaseMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None

    def test_existing_database_gains_audit_table_without_data_loss(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "CREATE TABLE app_settings (key TEXT PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 0, value TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')"
            )
            conn.execute(
                "INSERT INTO app_settings (key, user_id, value) VALUES ('legacy', 7, 'keep-me')"
            )
            conn.commit()
        finally:
            conn.close()

        db.init_db()

        legacy = db.fetch_one(
            "SELECT user_id, value FROM app_settings WHERE key = 'legacy'"
        )
        self.assertEqual(legacy, {"user_id": 7, "value": "keep-me"})
        with db.managed_connection() as conn:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(mcp_audit_logs)").fetchall()
            }
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(mcp_audit_logs)").fetchall()
            }
        self.assertEqual(
            columns,
            {
                "id",
                "user_id",
                "request_id",
                "tool_name",
                "operation_type",
                "target_type",
                "target_id",
                "success",
                "permission_result",
                "summary",
                "created_at",
            },
        )
        self.assertIn("idx_mcp_audit_logs_user_created", indexes)
        self.assertIn("idx_mcp_audit_logs_user_request", indexes)

    def test_mcp_database_initialization_is_idempotent(self):
        db.init_db()
        db.insert_and_get_id(
            """
            INSERT INTO mcp_audit_logs (
                user_id, request_id, tool_name, operation_type,
                target_type, target_id, success, permission_result, summary
            )
            VALUES (7, 'request-1', 'study_get_current_context', 'READ',
                    'context', '', 1, 'allowed', 'context=active')
            """
        )

        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()

        row = db.fetch_one(
            "SELECT COUNT(*) AS count FROM mcp_audit_logs WHERE request_id = 'request-1'"
        )
        self.assertEqual(row["count"], 1)


if __name__ == "__main__":
    unittest.main()
