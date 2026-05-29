import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import auth_service, ppt_context_service, ppt_service, review_service


class _SessionState(dict):
    pass


class _FakeStreamlit:
    def __init__(self):
        self.session_state = _SessionState()
        self.context = type("Context", (), {"cookies": {}})()


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
        state["auth_session_token"] = "token"
        state["auth_session_expires_at"] = 123
        state["ppt_generation_task"] = {"status": "running", "api_key": "secret"}
        state["ppt_structure_task"] = {"status": "running", "api_key": "secret"}
        state["study_asset_task_9"] = {"status": "running", "api_key": "secret"}
        state["ppt_reader_active_slide_9"] = 3
        state["unrelated_filter"] = "keep"

        auth_service.logout()

        self.assertNotIn("current_user", state)
        self.assertNotIn("auth_session_token", state)
        self.assertEqual(state["auth_session_expires_at"], 0)
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

    def test_deck_sections_are_user_scoped(self):
        alice_id = auth_service.create_user("alice", "pw")
        bob_id = auth_service.create_user("bob", "pw")
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, file_path)
            VALUES (?, 'alice.pdf', 'Alice Deck', ?)
            """,
            (alice_id, str(self.data_dir / "uploads" / "user_1" / "alice.pdf")),
        )
        db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title)
            VALUES (?, ?, 1, '第一页')
            """,
            (alice_id, deck_id),
        )
        structure = {
            "outline": "大纲",
            "sections": [
                {
                    "section_index": 1,
                    "title": "第一章",
                    "start_slide": 1,
                    "end_slide": 1,
                }
            ],
            "pages": [{"slide_number": 1, "section_index": 1, "page_type": "正文页"}],
        }

        with self.assertRaises(PermissionError):
            ppt_context_service.save_deck_structure(deck_id, structure, user_id=bob_id)

        ppt_context_service.save_deck_structure(deck_id, structure, user_id=alice_id)

        self.assertEqual(len(ppt_context_service.fetch_deck_sections(deck_id, user_id=alice_id)), 1)
        self.assertEqual(ppt_context_service.fetch_deck_sections(deck_id, user_id=bob_id), [])
        section = db.fetch_one("SELECT user_id FROM ppt_sections WHERE deck_id = ?", (deck_id,))
        self.assertEqual(section["user_id"], alice_id)

    def test_delete_user_removes_database_rows_atomically_and_only_unlinks_data_files(self):
        user_id = auth_service.create_user("alice", "pw")
        upload_dir = self.data_dir / "uploads" / f"user_{user_id}"
        image_dir = self.data_dir / "page_images" / f"user_{user_id}" / "deck"
        upload_dir.mkdir(parents=True)
        image_dir.mkdir(parents=True)
        deck_file = upload_dir / "deck.pdf"
        image_file = image_dir / "page_001.png"
        outside_file = Path(self.tmp.name).parent / "outside_should_survive.txt"
        deck_file.write_bytes(b"deck")
        image_file.write_bytes(b"image")
        outside_file.write_text("keep", encoding="utf-8")
        self.addCleanup(lambda: outside_file.exists() and outside_file.unlink())

        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, file_path)
            VALUES (?, 'deck.pdf', 'Deck', ?)
            """,
            (user_id, str(deck_file)),
        )
        db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, image_path)
            VALUES (?, ?, 1, ?)
            """,
            (user_id, deck_id, str(image_file)),
        )
        db.insert_and_get_id(
            """
            INSERT INTO ppt_sections (user_id, deck_id, section_index, title, start_slide, end_slide)
            VALUES (?, ?, 1, '章节', 1, 1)
            """,
            (user_id, deck_id),
        )
        db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, file_path)
            VALUES (?, 'bad.pdf', 'Bad Path', ?)
            """,
            (user_id, str(outside_file)),
        )
        secret_path = self.data_dir / f"api_keys_user_{user_id}.enc.json"
        secret_path.write_text("{}", encoding="utf-8")

        auth_service.delete_user_and_data(user_id)

        self.assertIsNone(db.fetch_one("SELECT id FROM users WHERE id = ?", (user_id,)))
        self.assertIsNone(db.fetch_one("SELECT id FROM ppt_sections WHERE user_id = ?", (user_id,)))
        self.assertFalse(deck_file.exists())
        self.assertFalse(image_file.exists())
        self.assertFalse(secret_path.exists())
        self.assertTrue(outside_file.exists())

    def test_device_session_restores_new_streamlit_session_before_idle_timeout(self):
        auth_service.create_user("alice", "pw")
        auth_service.login("alice", "pw")
        token = auth_service.st.session_state["auth_session_token"]

        auth_service.st.session_state.clear()
        auth_service.st.context.cookies = {auth_service.AUTH_SESSION_COOKIE_NAME: token}

        user = auth_service.restore_current_user_from_device_session(now=100)

        self.assertIsNotNone(user)
        self.assertEqual(user.username, "alice")
        self.assertEqual(auth_service.st.session_state["current_user"]["username"], "alice")

    def test_device_session_expires_after_five_minutes_without_activity(self):
        auth_service.create_user("alice", "pw")
        token = auth_service._issue_device_session(1, now=100)
        auth_service.st.session_state.clear()
        auth_service.st.context.cookies = {auth_service.AUTH_SESSION_COOKIE_NAME: token}

        user = auth_service.restore_current_user_from_device_session(now=401)

        self.assertIsNone(user)
        self.assertNotIn("current_user", auth_service.st.session_state)
        row = db.fetch_one("SELECT revoked_at FROM auth_sessions WHERE token_hash = ?", (auth_service._auth_token_hash(token),))
        self.assertEqual(row["revoked_at"], 401)

    def test_browser_activity_ping_extends_device_session(self):
        auth_service.create_user("alice", "pw")
        token = auth_service._issue_device_session(1, now=100)

        self.assertTrue(auth_service.record_browser_activity_ping(token, activity_at=350, now=360))
        auth_service.st.session_state.clear()
        auth_service.st.context.cookies = {auth_service.AUTH_SESSION_COOKIE_NAME: token}

        user = auth_service.restore_current_user_from_device_session(now=500)

        self.assertIsNotNone(user)
        self.assertEqual(user.username, "alice")

    def test_browser_cookie_activity_extends_existing_streamlit_session(self):
        auth_service.create_user("alice", "pw")
        auth_service.login("alice", "pw")
        token = auth_service.st.session_state["auth_session_token"]
        auth_service.st.context.cookies = {
            auth_service.AUTH_SESSION_COOKIE_NAME: f"{token}:350000"
        }

        user = auth_service.refresh_device_session_activity(now=360)

        self.assertIsNotNone(user)
        self.assertEqual(user.username, "alice")
        row = db.fetch_one(
            "SELECT last_seen_at, revoked_at FROM auth_sessions WHERE token_hash = ?",
            (auth_service._auth_token_hash(token),),
        )
        self.assertGreaterEqual(row["last_seen_at"], 350)
        self.assertIsNone(row["revoked_at"])


if __name__ == "__main__":
    unittest.main()
