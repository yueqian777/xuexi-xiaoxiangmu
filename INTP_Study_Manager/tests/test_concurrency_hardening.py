import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import auth_service, ppt_service, review_service


class _SessionState(dict):
    pass


class _FakeStreamlit:
    def __init__(self):
        self.session_state = _SessionState()


class ConcurrencyHardeningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
            patch.object(ppt_service, "UPLOAD_DIR", self.data_dir / "uploads"),
            patch.object(ppt_service, "PAGE_IMAGE_DIR", self.data_dir / "page_images"),
            patch.object(auth_service, "st", _FakeStreamlit()),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()

    def test_register_by_invite_consumes_invite_and_creates_user_atomically(self):
        admin_id = auth_service.create_user("admin", "pw", role="admin")
        code = auth_service.create_invite(created_by=admin_id, max_uses=1)

        user = auth_service.register_by_invite("alice", "pw", code)

        self.assertEqual(user.username, "alice")
        invite = db.fetch_one("SELECT used_count FROM invites WHERE code = ?", (code,))
        self.assertEqual(invite["used_count"], 1)
        with self.assertRaisesRegex(ValueError, "使用次数已满"):
            auth_service.register_by_invite("bob", "pw", code)
        self.assertIsNone(db.fetch_one("SELECT id FROM users WHERE username = ?", ("bob",)))

    def test_sensitive_session_cleanup_removes_background_tasks(self):
        state = auth_service.st.session_state
        state["current_user"] = {"id": 1}
        state["ppt_generation_task"] = {"status": "running", "api_key": "secret"}
        state["ppt_structure_task"] = {"status": "running", "api_key": "secret"}
        state["study_asset_task_9"] = {"status": "running", "api_key": "secret"}
        state["ppt_reader_active_slide_9"] = 3
        state["unrelated_filter"] = "keep"

        auth_service.logout()

        self.assertNotIn("current_user", state)
        self.assertNotIn("ppt_generation_task", state)
        self.assertNotIn("ppt_structure_task", state)
        self.assertNotIn("study_asset_task_9", state)
        self.assertNotIn("ppt_reader_active_slide_9", state)
        self.assertEqual(state["unrelated_filter"], "keep")

    def test_uploaded_deck_paths_are_user_scoped_and_unique(self):
        auth_service.create_user("alice", "pw")
        auth_service.login("alice", "pw")
        first = io.BytesIO(b"first")
        second = io.BytesIO(b"second")
        first.name = "same.pdf"
        second.name = "same.pdf"

        first_path = ppt_service.save_uploaded_deck(first)
        second_path = ppt_service.save_uploaded_deck(second)

        self.assertNotEqual(first_path, second_path)
        self.assertIn("user_1", str(first_path))
        self.assertEqual(first_path.read_bytes(), b"first")
        self.assertEqual(second_path.read_bytes(), b"second")

    def test_initial_review_tasks_are_idempotent(self):
        user_id = auth_service.create_user("alice", "pw")
        knowledge_id = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (user_id, subject, topic, one_sentence)
            VALUES (?, '数学', '极限', '一句话')
            """,
            (user_id,),
        )

        review_service.create_initial_review_tasks(knowledge_id, "2026-05-28", user_id=user_id)
        review_service.create_initial_review_tasks(knowledge_id, "2026-05-28", user_id=user_id)

        count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM review_tasks WHERE user_id = ? AND knowledge_id = ?",
            (user_id, knowledge_id),
        )
        self.assertEqual(count["count"], 4)


if __name__ == "__main__":
    unittest.main()
