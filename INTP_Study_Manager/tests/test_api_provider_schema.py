import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class ApiProviderSchemaTest(unittest.TestCase):
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

    def test_new_database_has_provider_vision_capability_column(self):
        db.init_db()

        conn = sqlite3.connect(self.db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(api_providers)").fetchall()}
            conn.execute(
                """
                INSERT INTO api_providers (provider_key, name, provider_type)
                VALUES ('custom', 'Custom', 'openai_chat')
                """
            )
            value = conn.execute(
                "SELECT vision_capability FROM api_providers WHERE provider_key = 'custom'"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertIn("vision_capability", columns)
        self.assertEqual(value, "auto")


if __name__ == "__main__":
    unittest.main()
