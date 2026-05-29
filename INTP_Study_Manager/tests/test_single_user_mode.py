import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import auth_service


APP_ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = APP_ROOT / "app.py"


class SingleUserModeTest(unittest.TestCase):
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
        db._INITIALIZED_DATABASE_PATH = None

    def test_require_login_returns_local_admin_without_account_tables(self):
        db.init_db()

        user = auth_service.require_login()

        self.assertEqual(user.id, 0)
        self.assertEqual(user.username, "local")
        self.assertEqual(user.role, "admin")

    def test_require_login_reuses_single_existing_account_id(self):
        db.init_db()
        with db.managed_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    display_name TEXT,
                    password_hash TEXT,
                    role TEXT,
                    is_active INTEGER
                )
                """
            )
            conn.execute("DELETE FROM users")
            conn.execute(
                """
                INSERT INTO users (id, username, display_name, password_hash, role, is_active)
                VALUES (7, 'alice', 'Alice', 'unused', 'user', 1)
                """
            )

        user = auth_service.require_login()

        self.assertEqual(user.id, 7)
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.display_name, "Alice")
        self.assertEqual(user.role, "admin")

    def test_new_database_does_not_create_account_tables(self):
        db.init_db()

        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            conn.close()

        self.assertNotIn("users", tables)
        self.assertNotIn("invites", tables)
        self.assertNotIn("auth_sessions", tables)

    def test_app_no_longer_references_login_or_admin_gate(self):
        source = APP_SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_page_names = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "pages"
            for alias in node.names
        }

        self.assertNotIn("admin_panel", imported_page_names)
        self.assertNotIn("ADMIN_PAGES", source)
        self.assertNotIn("_render_auth_gate", source)
        self.assertNotIn("_render_first_admin_setup", source)
        self.assertNotIn("_install_auth_session_browser_guard", source)


if __name__ == "__main__":
    unittest.main()
