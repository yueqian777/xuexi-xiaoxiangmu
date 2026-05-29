import unittest
from contextlib import contextmanager
from unittest.mock import patch

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
        query, params = conn.calls[0]
        self.assertIn("INSERT INTO slide_questions", query)
        self.assertIn("quote_text", query)
        self.assertIn("root_question_id", query)
        self.assertEqual(params, (4, 9, "问题", "引用", "答案", "模型", None, None, 0, "slide", None))
        update_query, update_params = conn.calls[1]
        self.assertIn("UPDATE slide_questions", update_query)
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
        query, params = conn.calls[1]
        self.assertIn("parent_question_id", query)
        self.assertEqual(params, (4, 9, "子问题", "回答片段", "子答案", "模型", 88, 77, 2, "question_answer", 77))
        self.assertEqual(len(conn.calls), 2)

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


if __name__ == "__main__":
    unittest.main()
