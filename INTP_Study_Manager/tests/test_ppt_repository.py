import unittest
from contextlib import contextmanager
from pathlib import Path
import tempfile
from unittest.mock import patch

import db
from repositories import ppt_repository


class FakeConnection:
    def __init__(self, lastrowid: int = 88, rows: list[dict] | None = None):
        self.lastrowid = lastrowid
        self.rows = rows or []
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, query, params=()):
        self.calls.append((query, tuple(params)))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def fake_transaction(conn: FakeConnection):
    @contextmanager
    def _transaction(*, attempts=None):
        yield conn

    return _transaction


class RowLike:
    def __init__(self, values: dict):
        self.values = values

    def __getitem__(self, key):
        return self.values[key]


class PptRepositoryTest(unittest.TestCase):
    def test_add_slide_explanation_normalizes_ids_and_returns_insert_id(self):
        with patch.object(ppt_repository, "insert_and_get_id", return_value=77) as insert_and_get_id:
            result = ppt_repository.add_slide_explanation("4", "9", "模型", "讲解")

        self.assertEqual(result, 77)
        query, params = insert_and_get_id.call_args.args
        self.assertIn("INSERT INTO slide_explanations", query)
        self.assertEqual(params, (4, 9, "模型", "讲解"))

    def test_add_slide_question_normalizes_ids_and_returns_insert_id(self):
        conn = FakeConnection(lastrowid=88)
        with patch.object(ppt_repository, "write_transaction", fake_transaction(conn)):
            result = ppt_repository.add_slide_question("4", "9", "问题", "答案", "模型", quote_text="引用")

        self.assertEqual(result, 88)
        query, params = next(call for call in conn.calls if "INSERT INTO slide_questions" in call[0])
        self.assertIn("INSERT INTO slide_questions", query)
        self.assertIn("quote_text", query)
        self.assertIn("root_question_id", query)
        self.assertIn("sort_order", query)
        self.assertEqual(params[-1], 1)
        params = params[:-1]
        self.assertEqual(params, (4, 9, "问题", "引用", "答案", "模型", None, None, 0, "slide", None))
        update_query, update_params = next(call for call in conn.calls if "UPDATE slide_questions" in call[0])
        self.assertIn("UPDATE slide_questions", update_query)
        update_params = (update_params[0], update_params[-1])
        self.assertEqual(update_params, (88, 88))

    def test_add_slide_question_saves_child_question_lineage(self):
        conn = FakeConnection(lastrowid=99, rows=[{"id": 77, "slide_id": 9, "root_question_id": 88, "depth": 1}])
        with patch.object(ppt_repository, "write_transaction", fake_transaction(conn)):
            result = ppt_repository.add_slide_question(
                "4",
                "9",
                "子问题",
                "子答案",
                "模型",
                quote_text="回答片段",
                root_question_id="88",
                parent_question_id="77",
                depth=2,
                quote_source="question_answer",
                quote_source_question_id="77",
            )

        self.assertEqual(result, 99)
        query, params = next(call for call in conn.calls if "INSERT INTO slide_questions" in call[0])
        self.assertIn("parent_question_id", query)
        self.assertIn("sort_order", query)
        self.assertEqual(params[-1], 1)
        params = params[:-1]
        self.assertEqual(params, (4, 9, "子问题", "回答片段", "子答案", "模型", 88, 77, 2, "question_answer", 77))
        self.assertGreaterEqual(len(conn.calls), 2)

    def test_latest_explanations_by_slide_ids_returns_empty_for_no_ids(self):
        with patch.object(ppt_repository, "fetch_all") as fetch_all:
            self.assertEqual(ppt_repository.latest_explanations_by_slide_ids(4, []), {})

        fetch_all.assert_not_called()

    def test_latest_explanations_by_slide_ids_groups_by_slide_id(self):
        rows = [
            {"id": 11, "slide_id": 7, "model": "模型", "explanation": "讲解", "created_at": "today"},
        ]
        with patch.object(ppt_repository, "fetch_all", return_value=rows) as fetch_all:
            result = ppt_repository.latest_explanations_by_slide_ids("4", ["7"])

        self.assertEqual(result, {7: rows[0]})
        query, params = fetch_all.call_args.args
        self.assertIn("ROW_NUMBER()", query)
        self.assertEqual(params, (4, 7))

    def test_update_slide_bookmark_can_toggle_and_rename(self):
        with patch.object(ppt_repository, "execute") as execute:
            ppt_repository.update_slide_bookmark("4", "9", enabled=True, title="  My bookmark  ")

        query, params = execute.call_args.args
        self.assertIn("UPDATE ppt_slides", query)
        self.assertIn("bookmark_enabled = ?", query)
        self.assertIn("bookmark_title = ?", query)
        self.assertEqual(params, (1, "My bookmark", 9, 4))

    def test_update_slide_bookmark_can_toggle_without_overwriting_title(self):
        with patch.object(ppt_repository, "execute") as execute:
            ppt_repository.update_slide_bookmark("4", "9", enabled=False)

        query, params = execute.call_args.args
        self.assertIn("bookmark_enabled = ?", query)
        self.assertNotIn("bookmark_title = ?", query)
        self.assertEqual(params, (0, 9, 4))

    def test_questions_by_slide_ids_returns_empty_lists_for_requested_slides(self):
        with patch.object(ppt_repository, "fetch_all", return_value=[]):
            result = ppt_repository.questions_by_slide_ids(4, [7, 8])

        self.assertEqual(result, {7: [], 8: []})

    def test_questions_by_slide_ids_groups_rows_in_repository(self):
        rows = [
            {
                "id": 12,
                "slide_id": 7,
                "question": "问题",
                "quote_text": "引用",
                "answer": "答案",
                "model": "模型",
                "category": "",
                "status": "未整理",
                "sort_order": 0,
                "root_question_id": 12,
                "parent_question_id": None,
                "depth": 0,
                "quote_source": "slide",
                "quote_source_question_id": None,
                "created_at": "today",
            },
        ]
        with patch.object(ppt_repository, "fetch_all", return_value=rows) as fetch_all:
            result = ppt_repository.questions_by_slide_ids("4", ["7"])

        self.assertEqual(result, {7: rows})
        query, params = fetch_all.call_args.args
        self.assertIn("quote_text", query)
        self.assertIn("root_question_id", query)
        self.assertIn("parent_question_id", query)
        self.assertIn("depth", query)
        self.assertIn("sort_order ASC", query)
        self.assertIn("created_at ASC", query)
        self.assertIn("id ASC", query)
        self.assertEqual(params, (4, 7))

    def test_flatten_question_subtree_reparents_nested_descendants_to_anchor(self):
        target = {
            "id": 10,
            "parent_question_id": None,
            "root_question_id": 10,
            "depth": 0,
            "sort_order": 0,
        }
        nested_descendants = [
            {"id": 21},
            {"id": 22},
        ]
        conn = FakeConnection(rows=[target])

        def execute(query, params=()):
            conn.calls.append((query, tuple(params)))
            if "WITH RECURSIVE descendants" in query:
                return FakeConnection(rows=nested_descendants)
            if "SELECT COALESCE(MAX(sort_order)" in query:
                return FakeConnection(rows=[{"max_order": 5}])
            if "SELECT id, root_question_id" in query:
                return FakeConnection(rows=[target])
            return FakeConnection(rows=[])

        conn.execute = execute
        with patch.object(ppt_repository, "write_transaction", fake_transaction(conn)):
            count = ppt_repository.flatten_question_subtree("4", "10")

        self.assertEqual(count, 2)
        update_calls = [call for call in conn.calls if "UPDATE slide_questions" in call[0]]
        self.assertEqual(len(update_calls), 2)
        self.assertEqual(update_calls[0][1], (10, 10, 1, 6, 21, 4))
        self.assertEqual(update_calls[-1][1], (10, 10, 1, 7, 22, 4))

    def test_flatten_question_subtree_reads_sqlite_row_without_dict_get(self):
        target = RowLike(
            {
                "id": 20,
                "parent_question_id": None,
                "root_question_id": 10,
                "depth": 0,
                "sort_order": 0,
            }
        )
        conn = FakeConnection(rows=[target])

        def execute(query, params=()):
            conn.calls.append((query, tuple(params)))
            if "WITH RECURSIVE descendants" in query:
                return FakeConnection(rows=[RowLike({"id": 21})])
            if "SELECT COALESCE(MAX(sort_order)" in query:
                return FakeConnection(rows=[RowLike({"max_order": 5})])
            if "SELECT id, root_question_id" in query:
                return FakeConnection(rows=[target])
            return FakeConnection(rows=[])

        conn.execute = execute
        with patch.object(ppt_repository, "write_transaction", fake_transaction(conn)):
            count = ppt_repository.flatten_question_subtree("4", "20")

        self.assertEqual(count, 1)

    def test_delete_slide_question_thread_deletes_question_and_descendants(self):
        conn = FakeConnection(rows=[])

        def execute(query, params=()):
            conn.calls.append((query, tuple(params)))
            if "WITH RECURSIVE subtree" in query and "SELECT id" in query:
                return FakeConnection(rows=[{"id": 10}, {"id": 11}, {"id": 12}])
            return FakeConnection(rows=[])

        conn.execute = execute
        with patch.object(ppt_repository, "write_transaction", fake_transaction(conn)):
            count = ppt_repository.delete_slide_question_thread("4", "10")

        self.assertEqual(count, 3)
        delete_calls = [call for call in conn.calls if "DELETE FROM slide_questions" in call[0]]
        self.assertEqual(len(delete_calls), 1)
        self.assertEqual(delete_calls[0][1], (4, 10, 11, 12))


class PptRepositorySqliteIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.data_dir_patch = patch.object(db, "DATA_DIR", self.data_dir)
        self.db_path_patch = patch.object(db, "DATABASE_PATH", self.db_path)
        self.data_dir_patch.start()
        self.db_path_patch.start()
        self.addCleanup(self.data_dir_patch.stop)
        self.addCleanup(self.db_path_patch.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()
        self.slide_id = self._create_slide()

    def _create_slide(self, *, user_id: int = 11) -> int:
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, file_path, slide_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, "deck.pdf", "Deck", "deck.pdf", 1),
        )
        return db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, deck_id, 1, "Slide 1"),
        )

    def _question_row(self, question_id: int) -> dict:
        row = db.fetch_one("SELECT * FROM slide_questions WHERE id = ?", (question_id,))
        self.assertIsNotNone(row)
        return row

    def test_create_slide_question_tree_node_persists_root_child_depth_and_sort_order(self):
        root_1 = ppt_repository.create_slide_question_tree_node(
            11,
            self.slide_id,
            "root 1",
            "answer 1",
            "model",
        )
        root_2 = ppt_repository.create_slide_question_tree_node(
            11,
            self.slide_id,
            "root 2",
            "answer 2",
            "model",
        )
        child_1 = ppt_repository.create_slide_question_tree_node(
            11,
            self.slide_id,
            "child 1",
            "child answer 1",
            "model",
            parent_question_id=root_1,
        )
        child_2 = ppt_repository.create_slide_question_tree_node(
            11,
            self.slide_id,
            "child 2",
            "child answer 2",
            "model",
            parent_question_id=root_1,
        )
        grandchild = ppt_repository.create_slide_question_tree_node(
            11,
            self.slide_id,
            "grandchild",
            "grandchild answer",
            "model",
            parent_question_id=child_1,
        )

        root_1_row = self._question_row(root_1)
        root_2_row = self._question_row(root_2)
        child_1_row = self._question_row(child_1)
        child_2_row = self._question_row(child_2)
        grandchild_row = self._question_row(grandchild)

        self.assertEqual(root_1_row["root_question_id"], root_1)
        self.assertIsNone(root_1_row["parent_question_id"])
        self.assertEqual(root_1_row["depth"], 0)
        self.assertEqual(root_1_row["sort_order"], 1)
        self.assertEqual(root_2_row["sort_order"], 2)

        self.assertEqual(child_1_row["parent_question_id"], root_1)
        self.assertEqual(child_1_row["root_question_id"], root_1)
        self.assertEqual(child_1_row["depth"], 1)
        self.assertEqual(child_1_row["sort_order"], 1)
        self.assertEqual(child_2_row["sort_order"], 2)

        self.assertEqual(grandchild_row["parent_question_id"], child_1)
        self.assertEqual(grandchild_row["root_question_id"], root_1)
        self.assertEqual(grandchild_row["depth"], 2)
        self.assertEqual(grandchild_row["sort_order"], 1)

    def test_get_slide_question_tree_returns_complete_nested_tree_after_reload(self):
        root = ppt_repository.create_slide_question_tree_node(11, self.slide_id, "root", "answer", "model")
        child = ppt_repository.create_slide_question_tree_node(
            11,
            self.slide_id,
            "child",
            "child answer",
            "model",
            parent_question_id=root,
        )
        grandchild = ppt_repository.create_slide_question_tree_node(
            11,
            self.slide_id,
            "grandchild",
            "grandchild answer",
            "model",
            parent_question_id=child,
        )

        first_load = ppt_repository.get_slide_question_tree(self.slide_id, 11)
        second_load = ppt_repository.get_slide_question_tree(self.slide_id, 11)

        for tree in (first_load, second_load):
            self.assertEqual([node["id"] for node in tree], [root])
            self.assertEqual([node["id"] for node in tree[0]["children"]], [child])
            self.assertEqual([node["id"] for node in tree[0]["children"][0]["children"]], [grandchild])

    def test_close_slide_question_only_changes_status(self):
        root = ppt_repository.create_slide_question_tree_node(11, self.slide_id, "root", "answer", "model")
        child = ppt_repository.create_slide_question_tree_node(
            11,
            self.slide_id,
            "child",
            "child answer",
            "model",
            parent_question_id=root,
        )

        before = self._question_row(child)
        changed = ppt_repository.close_slide_question(child, 11)
        after = self._question_row(child)

        self.assertTrue(changed)
        self.assertEqual(after["status"], "closed")
        self.assertEqual(after["parent_question_id"], before["parent_question_id"])
        self.assertEqual(after["root_question_id"], before["root_question_id"])
        self.assertEqual(after["depth"], before["depth"])
        self.assertEqual(after["sort_order"], before["sort_order"])
        tree = ppt_repository.get_slide_question_tree(self.slide_id, 11)
        self.assertEqual(tree[0]["children"][0]["id"], child)

    def test_normalize_slide_question_tree_repairs_legacy_root_depth_and_sort_order(self):
        root = db.insert_and_get_id(
            """
            INSERT INTO slide_questions (
                user_id, slide_id, question, answer, model,
                root_question_id, parent_question_id, depth, sort_order, created_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
            """,
            (11, self.slide_id, "legacy root", "answer", "model", 4, 0, "2026-01-01 10:00:00"),
        )
        child_a = db.insert_and_get_id(
            """
            INSERT INTO slide_questions (
                user_id, slide_id, question, answer, model,
                root_question_id, parent_question_id, depth, sort_order, created_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (11, self.slide_id, "legacy child a", "answer", "model", root, 0, 0, "2026-01-01 10:01:00"),
        )
        child_b = db.insert_and_get_id(
            """
            INSERT INTO slide_questions (
                user_id, slide_id, question, answer, model,
                root_question_id, parent_question_id, depth, sort_order, created_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (11, self.slide_id, "legacy child b", "answer", "model", root, 0, 0, "2026-01-01 10:02:00"),
        )
        grandchild = db.insert_and_get_id(
            """
            INSERT INTO slide_questions (
                user_id, slide_id, question, answer, model,
                root_question_id, parent_question_id, depth, sort_order, created_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (11, self.slide_id, "legacy grandchild", "answer", "model", child_a, 0, 0, "2026-01-01 10:03:00"),
        )

        ppt_repository.normalize_slide_question_tree(self.slide_id, 11)

        root_row = self._question_row(root)
        child_a_row = self._question_row(child_a)
        child_b_row = self._question_row(child_b)
        grandchild_row = self._question_row(grandchild)

        self.assertEqual(root_row["root_question_id"], root)
        self.assertEqual(root_row["depth"], 0)
        self.assertEqual(root_row["sort_order"], 1)
        self.assertEqual(child_a_row["root_question_id"], root)
        self.assertEqual(child_a_row["depth"], 1)
        self.assertEqual(child_a_row["sort_order"], 1)
        self.assertEqual(child_b_row["root_question_id"], root)
        self.assertEqual(child_b_row["depth"], 1)
        self.assertEqual(child_b_row["sort_order"], 2)
        self.assertEqual(grandchild_row["root_question_id"], root)
        self.assertEqual(grandchild_row["depth"], 2)
        self.assertEqual(grandchild_row["sort_order"], 1)


if __name__ == "__main__":
    unittest.main()
