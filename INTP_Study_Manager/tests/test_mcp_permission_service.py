import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from services import mcp_permission_service as permission_service


class McpPermissionServiceTest(unittest.TestCase):
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

    def test_default_permissions_match_the_local_mcp_policy(self):
        self.assertEqual(
            permission_service.get_permissions(7),
            {
                "read_current_context": True,
                "read_ppt": True,
                "read_question_tree": True,
                "read_knowledge_cards": True,
                "read_reviews": False,
                "write_slide_explanation": True,
                "write_slide_question": True,
                "write_knowledge_card": False,
                "write_review": False,
            },
        )

    def test_no_delete_permission_is_defined(self):
        self.assertFalse(
            any(key.startswith("delete") for key in permission_service.DEFAULT_PERMISSIONS)
        )
        with self.assertRaisesRegex(ValueError, "未知"):
            permission_service.update_permissions(7, {"delete_slide": True})

    def test_permission_updates_are_persisted_and_merged_with_defaults(self):
        updated = permission_service.update_permissions(
            7,
            {"read_reviews": True, "write_slide_explanation": False},
        )

        self.assertTrue(updated["read_reviews"])
        self.assertFalse(updated["write_slide_explanation"])
        self.assertTrue(updated["read_ppt"])
        self.assertEqual(permission_service.get_permissions(7), updated)

    def test_permissions_are_isolated_by_explicit_user_scope(self):
        permission_service.update_permissions(7, {"read_reviews": True})
        permission_service.update_permissions(8, {"write_review": True})

        user_seven = permission_service.get_permissions(7)
        user_eight = permission_service.get_permissions(8)
        self.assertTrue(user_seven["read_reviews"])
        self.assertFalse(user_seven["write_review"])
        self.assertFalse(user_eight["read_reviews"])
        self.assertTrue(user_eight["write_review"])

        rows = db.fetch_all(
            "SELECT key, user_id FROM app_settings WHERE key LIKE '%:mcp_permissions' ORDER BY user_id"
        )
        self.assertEqual(
            rows,
            [
                {"key": "user:7:mcp_permissions", "user_id": 7},
                {"key": "user:8:mcp_permissions", "user_id": 8},
            ],
        )

    def test_read_requires_both_the_namespaced_key_and_user_id(self):
        db.execute(
            "INSERT INTO app_settings (key, user_id, value) VALUES (?, ?, ?)",
            (
                "user:7:mcp_permissions",
                8,
                json.dumps({"read_reviews": True}),
            ),
        )

        self.assertFalse(permission_service.get_permissions(7)["read_reviews"])

    def test_upsert_refuses_to_take_over_a_namespaced_key_owned_by_another_user(self):
        db.execute(
            "INSERT INTO app_settings (key, user_id, value) VALUES (?, ?, ?)",
            ("user:7:mcp_permissions", 8, "{}"),
        )

        with self.assertRaises(permission_service.PermissionStorageError):
            permission_service.update_permissions(7, {"read_reviews": True})

        row = db.fetch_one(
            "SELECT user_id, value FROM app_settings WHERE key = ?",
            ("user:7:mcp_permissions",),
        )
        self.assertEqual(row, {"user_id": 8, "value": "{}"})

    def test_updates_require_real_booleans(self):
        for bad_value in (1, 0, "true", None, [], {}):
            with self.subTest(value=bad_value):
                with self.assertRaisesRegex(ValueError, "布尔"):
                    permission_service.update_permissions(
                        7, {"read_reviews": bad_value}
                    )

    def test_unknown_permission_keys_are_rejected_without_writing(self):
        with self.assertRaisesRegex(ValueError, "未知"):
            permission_service.update_permissions(7, {"read_everything": True})

        self.assertIsNone(
            db.fetch_one(
                "SELECT key FROM app_settings WHERE key = ?",
                ("user:7:mcp_permissions",),
            )
        )

    def test_existing_corrupt_or_non_object_permission_payload_fails_closed(self):
        key = "user:7:mcp_permissions"
        db.execute(
            "INSERT INTO app_settings (key, user_id, value) VALUES (?, ?, ?)",
            (key, 7, "{not-json"),
        )
        invalid_payloads = [
            "{not-json",
            "null",
            "[]",
            '"permissions"',
            "true",
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                db.execute(
                    "UPDATE app_settings SET value = ? WHERE key = ? AND user_id = ?",
                    (payload, key, 7),
                )
                with self.assertRaises(permission_service.PermissionStorageError):
                    permission_service.get_permissions(7)

    def test_any_known_permission_with_a_non_boolean_value_fails_closed(self):
        key = "user:7:mcp_permissions"
        db.execute(
            "INSERT INTO app_settings (key, user_id, value) VALUES (?, ?, ?)",
            (key, 7, "{}"),
        )

        for permission_key in permission_service.KNOWN_PERMISSION_KEYS:
            for bad_value in (1, 0, "true", None, [], {}):
                with self.subTest(permission_key=permission_key, value=bad_value):
                    db.execute(
                        "UPDATE app_settings SET value = ? WHERE key = ? AND user_id = ?",
                        (json.dumps({permission_key: bad_value}), key, 7),
                    )
                    with self.assertRaises(permission_service.PermissionStorageError):
                        permission_service.get_permissions(7)

    def test_update_refuses_to_replace_a_corrupt_existing_permission_record(self):
        key = "user:7:mcp_permissions"
        db.execute(
            "INSERT INTO app_settings (key, user_id, value) VALUES (?, ?, ?)",
            (key, 7, "{not-json"),
        )

        with self.assertRaises(permission_service.PermissionStorageError):
            permission_service.update_permissions(7, {"write_review": True})

        row = db.fetch_one(
            "SELECT value FROM app_settings WHERE key = ? AND user_id = ?",
            (key, 7),
        )
        self.assertEqual(row, {"value": "{not-json"})

    def test_incomplete_existing_permission_object_fails_closed(self):
        key = "user:7:mcp_permissions"
        for payload in ("{}", '{"read_ppt": true}'):
            with self.subTest(payload=payload):
                db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
                db.execute(
                    "INSERT INTO app_settings (key, user_id, value) VALUES (?, 7, ?)",
                    (key, payload),
                )
                with self.assertRaises(permission_service.PermissionStorageError):
                    permission_service.get_permissions(7)

    def test_is_allowed_and_require_permission_validate_permission_names(self):
        self.assertTrue(permission_service.is_allowed(7, "read_ppt"))
        self.assertFalse(permission_service.is_allowed(7, "read_reviews"))
        with self.assertRaises(permission_service.PermissionDeniedError) as raised:
            permission_service.require_permission(7, "read_reviews")
        self.assertEqual(raised.exception.permission_key, "read_reviews")
        with self.assertRaisesRegex(ValueError, "未知"):
            permission_service.is_allowed(7, "delete_anything")

    def test_stable_adapter_interface_names_delegate_to_the_same_policy(self):
        updated = permission_service.set_permissions(7, {"read_reviews": True})

        self.assertTrue(updated["read_reviews"])
        self.assertTrue(
            permission_service.is_permission_allowed(7, "read_reviews")
        )

    def test_user_id_must_be_a_non_negative_real_integer(self):
        for bad_user_id in (True, -1, 1.5, "not-an-id"):
            with self.subTest(user_id=bad_user_id):
                with self.assertRaisesRegex(ValueError, "user_id"):
                    permission_service.get_permissions(bad_user_id)


if __name__ == "__main__":
    unittest.main()
