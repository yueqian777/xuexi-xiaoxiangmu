from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client

import db
from services import active_learning_context_service
from services import mcp_permission_service


class StudyMcpServerProtocolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
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
        db.init_db()

        self.user_id = 41
        self.other_user_id = 42
        self.deck_id, self.slide_ids = self._create_deck(self.user_id, "Signals", 3)
        self.other_deck_id, self.other_slide_ids = self._create_deck(
            self.other_user_id, "Private", 2
        )
        active_learning_context_service.set_active_slide(
            self.user_id,
            self.deck_id,
            slide_id=self.slide_ids[1],
            slide_number=2,
        )

    def _create_deck(
        self, user_id: int, title: str, slide_count: int
    ) -> tuple[int, list[int]]:
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, filename, title, subject, file_path, slide_count
            )
            VALUES (?, ?, ?, 'DSP', ?, ?)
            """,
            (user_id, f"{title}.pdf", title, f"C:/private/{title}.pdf", slide_count),
        )
        slide_ids = []
        for number in range(1, slide_count + 1):
            slide_ids.append(
                db.insert_and_get_id(
                    """
                    INSERT INTO ppt_slides (
                        user_id, deck_id, slide_number, title, slide_text,
                        image_path, page_type, slide_role, key_points,
                        one_sentence_summary
                    )
                    VALUES (?, ?, ?, ?, ?, ?, '公式页', '核心页', ?, ?)
                    """,
                    (
                        user_id,
                        deck_id,
                        number,
                        f"Slide {number}",
                        f"Text {number}",
                        f"C:/private/{title}-{number}.png",
                        f"Point {number}",
                        f"Summary {number}",
                    ),
                )
            )
        return deck_id, slide_ids

    async def _call(self, tool_name: str, arguments: dict | None = None):
        from study_mcp.server import create_server

        async with Client(create_server(self.user_id), raise_exceptions=True) as client:
            return await client.call_tool(tool_name, arguments or {})

    async def test_protocol_exposes_exactly_the_fourteen_v1_tools_without_delete(self):
        from study_mcp.server import create_server

        expected = {
            "study_get_current_context",
            "study_get_current_slide",
            "study_read_slide_range",
            "study_get_question_tree",
            "study_get_knowledge_card",
            "study_search_knowledge",
            "study_get_today_reviews",
            "study_save_slide_explanation",
            "study_save_slide_explanations",
            "study_add_slide_question",
            "study_convert_question_to_knowledge",
            "study_mark_question_understood",
            "study_create_review_for_question",
            "study_submit_review_result",
        }
        async with Client(create_server(self.user_id), raise_exceptions=True) as client:
            result = await client.list_tools()

        tools = {tool.name: tool for tool in result.tools}
        self.assertEqual(set(tools), expected)
        self.assertFalse(any("delete" in name.lower() for name in tools))
        for tool in tools.values():
            self.assertNotIn("user_id", tool.input_schema.get("properties", {}))
            self.assertIsNotNone(tool.annotations)
            self.assertFalse(tool.annotations.destructive_hint)
            self.assertFalse(tool.annotations.open_world_hint)
            self.assertTrue(tool.description)
            for parameter in tool.input_schema.get("properties", {}):
                self.assertIn(
                    f"`{parameter}`",
                    tool.description,
                    f"{tool.name} description must explain {parameter}",
                )

    async def test_current_context_and_slide_are_structured_and_audited(self):
        context_result = await self._call("study_get_current_context")
        slide_result = await self._call(
            "study_get_current_slide",
            {"include_neighbor_context": True, "neighbor_radius": 1},
        )

        self.assertFalse(context_result.is_error)
        self.assertTrue(context_result.structured_content["ok"])
        self.assertEqual(context_result.structured_content["context"]["deck_id"], self.deck_id)
        self.assertTrue(slide_result.structured_content["ok"])
        slide = slide_result.structured_content["slide"]
        self.assertEqual(slide["slide_id"], self.slide_ids[1])
        self.assertEqual([item["slide_number"] for item in slide["neighbors"]], [1, 3])
        self.assertNotIn("file_path", repr(slide))
        self.assertNotIn("image_path", repr(slide))

        rows = db.fetch_all(
            "SELECT tool_name, operation_type, success FROM mcp_audit_logs WHERE user_id = ?",
            (self.user_id,),
        )
        self.assertEqual(
            [(row["tool_name"], row["operation_type"], row["success"]) for row in rows],
            [
                ("study_get_current_context", "READ", 1),
                ("study_get_current_slide", "READ", 1),
            ],
        )

    async def test_disabled_read_permission_returns_structured_denial_and_audits(self):
        mcp_permission_service.set_permissions(self.user_id, {"read_reviews": False})

        result = await self._call("study_get_today_reviews")

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "permission_denied")
        row = db.fetch_one(
            "SELECT * FROM mcp_audit_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (self.user_id,),
        )
        self.assertEqual(row["tool_name"], "study_get_today_reviews")
        self.assertEqual(row["permission_result"], "permission_denied")
        self.assertEqual(row["success"], 0)

    async def test_single_explanation_append_preserves_old_version_and_redacts_audit(self):
        old_id = db.insert_and_get_id(
            """
            INSERT INTO slide_explanations (user_id, slide_id, model, explanation)
            VALUES (?, ?, 'API', 'old version')
            """,
            (self.user_id, self.slide_ids[1]),
        )
        secret_body = "unique explanation body that must not appear in audit"

        result = await self._call(
            "study_save_slide_explanation",
            {
                "slide_id": self.slide_ids[1],
                "slide_number": 2,
                "deck_id": self.deck_id,
                "explanation": secret_body,
            },
        )

        self.assertTrue(result.structured_content["ok"])
        saved = result.structured_content["result"]
        self.assertGreater(saved["explanation_id"], old_id)
        rows = db.fetch_all(
            "SELECT model, explanation FROM slide_explanations WHERE user_id = ? AND slide_id = ? ORDER BY id",
            (self.user_id, self.slide_ids[1]),
        )
        self.assertEqual(rows[0], {"model": "API", "explanation": "old version"})
        self.assertEqual(rows[1], {"model": "ChatGPT MCP", "explanation": secret_body})
        audit = db.fetch_one(
            "SELECT summary FROM mcp_audit_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (self.user_id,),
        )
        self.assertNotIn(secret_body, audit["summary"])

    async def test_disabled_write_permission_cannot_mutate_database(self):
        mcp_permission_service.set_permissions(
            self.user_id, {"write_slide_explanation": False}
        )

        result = await self._call(
            "study_save_slide_explanation",
            {
                "slide_id": self.slide_ids[1],
                "slide_number": 2,
                "explanation": "must not be stored",
            },
        )

        self.assertEqual(result.structured_content["error"]["code"], "permission_denied")
        count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )
        self.assertEqual(count["count"], 0)

    async def test_batch_over_25_and_cross_user_slide_are_structured_failures(self):
        oversized = [
            {"slide_id": self.slide_ids[0], "slide_number": 1, "explanation": f"e{i}"}
            for i in range(26)
        ]
        too_many = await self._call(
            "study_save_slide_explanations",
            {"deck_id": self.deck_id, "slides": oversized},
        )
        cross_user = await self._call(
            "study_save_slide_explanation",
            {
                "slide_id": self.other_slide_ids[0],
                "slide_number": 1,
                "explanation": "private",
            },
        )

        self.assertEqual(too_many.structured_content["error"]["code"], "too_many_slides")
        self.assertEqual(cross_user.structured_content["error"]["code"], "not_found")
        count = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )
        self.assertEqual(count["count"], 0)

    async def test_tool_exceptions_are_redacted_to_structured_internal_error(self):
        with patch(
            "services.active_learning_context_service.get_active_context",
            side_effect=RuntimeError("private local path C:/secret"),
        ):
            result = await self._call("study_get_current_context")

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "internal_error")
        self.assertNotIn("C:/secret", repr(result.structured_content))
        audit = db.fetch_one(
            "SELECT success, summary FROM mcp_audit_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (self.user_id,),
        )
        self.assertEqual(audit["success"], 0)
        self.assertNotIn("C:/secret", audit["summary"])

    async def test_read_range_limits_and_cross_user_deck_are_enforced_by_tool(self):
        success = await self._call(
            "study_read_slide_range",
            {"deck_id": self.deck_id, "start_slide": 1, "end_slide": 3},
        )
        too_large = await self._call(
            "study_read_slide_range",
            {"deck_id": self.deck_id, "start_slide": 1, "end_slide": 26},
        )
        foreign = await self._call(
            "study_read_slide_range",
            {"deck_id": self.other_deck_id, "start_slide": 1, "end_slide": 2},
        )

        self.assertTrue(success.structured_content["ok"])
        self.assertEqual(
            [item["slide_number"] for item in success.structured_content["slides"]],
            [1, 2, 3],
        )
        self.assertEqual(
            too_large.structured_content["error"]["code"], "slide_range_too_large"
        )
        self.assertEqual(foreign.structured_content["error"]["code"], "resource_not_found")

    async def test_question_knowledge_and_review_tools_reuse_idempotent_workflows(self):
        root = await self._call(
            "study_add_slide_question",
            {
                "slide_id": self.slide_ids[0],
                "question": "What is ROC?",
                "answer": "A convergence region.",
            },
        )
        root_id = root.structured_content["result"]["question_id"]
        child = await self._call(
            "study_add_slide_question",
            {
                "slide_id": self.slide_ids[0],
                "question": "Why is it important?",
                "answer": "It determines stability.",
                "parent_question_id": root_id,
                "quote_text": "A convergence region.",
            },
        )
        child_id = child.structured_content["result"]["question_id"]
        tree = await self._call(
            "study_get_question_tree", {"slide_id": self.slide_ids[0]}
        )

        self.assertEqual(tree.structured_content["questions"][0]["id"], root_id)
        self.assertEqual(
            tree.structured_content["questions"][0]["children"][0]["id"], child_id
        )

        denied = await self._call(
            "study_convert_question_to_knowledge", {"question_id": root_id}
        )
        self.assertEqual(denied.structured_content["error"]["code"], "permission_denied")
        mcp_permission_service.set_permissions(
            self.user_id,
            {
                "write_knowledge_card": True,
                "write_review": True,
                "read_reviews": True,
            },
        )
        first = await self._call(
            "study_convert_question_to_knowledge", {"question_id": root_id}
        )
        second = await self._call(
            "study_convert_question_to_knowledge", {"question_id": root_id}
        )
        knowledge_id = first.structured_content["result"]["knowledge_id"]
        self.assertTrue(first.structured_content["result"]["created"])
        self.assertFalse(second.structured_content["result"]["created"])

        db.execute(
            "UPDATE review_tasks SET review_date = '2020-01-01' WHERE user_id = ? AND knowledge_id = ?",
            (self.user_id, knowledge_id),
        )

        understood = await self._call(
            "study_mark_question_understood", {"question_id": root_id}
        )
        ensured = await self._call(
            "study_create_review_for_question", {"question_id": root_id}
        )
        card = await self._call(
            "study_get_knowledge_card", {"knowledge_id": knowledge_id}
        )
        search = await self._call(
            "study_search_knowledge", {"query": "ROC", "subject": "DSP", "limit": 5}
        )
        today = await self._call("study_get_today_reviews")

        self.assertTrue(understood.structured_content["result"]["understood"])
        self.assertEqual(ensured.structured_content["result"]["knowledge_id"], knowledge_id)
        self.assertEqual(card.structured_content["knowledge"]["id"], knowledge_id)
        self.assertEqual(search.structured_content["results"][0]["id"], knowledge_id)
        self.assertGreaterEqual(today.structured_content["count"], 1)

        review_task_id = today.structured_content["reviews"][0]["review_task_id"]
        submitted = await self._call(
            "study_submit_review_result",
            {"review_task_id": review_task_id, "result": "基本掌握"},
        )
        self.assertTrue(submitted.structured_content["ok"])
        self.assertEqual(
            submitted.structured_content["result"]["review_task_id"], review_task_id
        )

    async def test_batch_is_atomic_and_stale_fingerprint_is_rejected(self):
        from services import chatgpt_explanation_task_service

        fingerprint = chatgpt_explanation_task_service.deck_fingerprint(
            self.user_id, self.deck_id
        )
        success = await self._call(
            "study_save_slide_explanations",
            {
                "deck_id": self.deck_id,
                "expected_deck_fingerprint": fingerprint,
                "slides": [
                    {
                        "slide_id": self.slide_ids[0],
                        "slide_number": 1,
                        "explanation": "first",
                    },
                    {
                        "slide_id": self.slide_ids[1],
                        "slide_number": 2,
                        "explanation": "second",
                    },
                ],
            },
        )
        self.assertEqual(len(success.structured_content["result"]["explanation_ids"]), 2)

        before = db.fetch_one(
            "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
            (self.user_id,),
        )["count"]
        invalid = await self._call(
            "study_save_slide_explanations",
            {
                "deck_id": self.deck_id,
                "slides": [
                    {
                        "slide_id": self.slide_ids[2],
                        "slide_number": 3,
                        "explanation": "would be rolled back",
                    },
                    {
                        "slide_id": self.other_slide_ids[0],
                        "slide_number": 1,
                        "explanation": "foreign",
                    },
                ],
            },
        )
        self.assertEqual(invalid.structured_content["error"]["code"], "not_found")
        self.assertEqual(
            db.fetch_one(
                "SELECT COUNT(*) AS count FROM slide_explanations WHERE user_id = ?",
                (self.user_id,),
            )["count"],
            before,
        )

        db.execute(
            "UPDATE ppt_slides SET slide_text = 'changed' WHERE user_id = ? AND id = ?",
            (self.user_id, self.slide_ids[2]),
        )
        stale = await self._call(
            "study_save_slide_explanation",
            {
                "deck_id": self.deck_id,
                "slide_id": self.slide_ids[2],
                "slide_number": 3,
                "explanation": "stale write",
                "expected_deck_fingerprint": fingerprint,
            },
        )
        self.assertEqual(
            stale.structured_content["error"]["code"], "stale_deck_fingerprint"
        )


if __name__ == "__main__":
    unittest.main()
