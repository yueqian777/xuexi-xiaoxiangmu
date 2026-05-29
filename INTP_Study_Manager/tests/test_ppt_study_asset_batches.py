import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from pages import ppt_tutor
from services.ai_service import AIServiceError


class PptStudyAssetBatchTest(unittest.TestCase):
    def test_init_db_backfills_user_scope_for_existing_study_asset_page_table(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name)
        db_path = data_dir / "study_manager.db"
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)

        with (
            patch.object(db, "DATA_DIR", data_dir),
            patch.object(db, "DATABASE_PATH", db_path),
        ):
            db._INITIALIZED_DATABASE_PATH = None
            db.init_db()
            with db.managed_connection() as conn:
                deck_id = conn.execute(
                    """
                    INSERT INTO ppt_decks (user_id, filename, title, file_path, slide_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (7, "deck.pdf", "Deck", "deck.pdf", 3),
                ).lastrowid
                conn.execute("DROP TABLE ppt_study_asset_pages")
                conn.execute(
                    """
                    CREATE TABLE ppt_study_asset_pages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        deck_id INTEGER NOT NULL,
                        slide_number INTEGER NOT NULL,
                        session_id INTEGER,
                        knowledge_count INTEGER NOT NULL DEFAULT 0,
                        range_label TEXT DEFAULT '',
                        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO ppt_study_asset_pages (
                        deck_id, slide_number, session_id, knowledge_count, range_label
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (deck_id, 3, None, 2, "page 3"),
                )

            db._INITIALIZED_DATABASE_PATH = None
            db.init_db()
            row = db.fetch_one(
                "SELECT user_id FROM ppt_study_asset_pages WHERE deck_id = ? AND slide_number = ?",
                (deck_id, 3),
            )
            completed_for_owner = ppt_tutor._completed_study_asset_slide_numbers(7, deck_id)
            completed_for_local = ppt_tutor._completed_study_asset_slide_numbers(0, deck_id)

        self.assertEqual(row["user_id"], 7)
        self.assertEqual(completed_for_owner, {3})
        self.assertEqual(completed_for_local, set())

    def test_running_study_asset_status_keeps_refreshing_when_throttled(self):
        class FakeColumn:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class FakeStreamlit:
            def __init__(self):
                self.rerun_called = False
                self.session_state = {}

            def columns(self, _spec):
                return [FakeColumn(), FakeColumn()]

            def info(self, _message):
                pass

            def progress(self, _value, text=""):
                pass

            def caption(self, _message):
                pass

            def button(self, _label, key=None):
                return False

            def rerun(self):
                self.rerun_called = True

        fake_st = FakeStreamlit()
        task = {
            "status": "running",
            "progress": 0.5,
            "status_text": "Generating unchanged batch",
            "completed_batches": 1,
            "batch_count": 2,
        }

        with (
            patch.object(ppt_tutor, "st", fake_st),
            patch.object(ppt_tutor, "_should_refresh_task", return_value=False),
            patch.object(ppt_tutor.time, "sleep") as sleep,
        ):
            ppt_tutor._render_study_asset_task_status(task, "task", "draft", "raw", "meta")

        sleep.assert_called_once()
        self.assertTrue(fake_st.rerun_called)

    def test_build_study_asset_batches_splits_by_sections(self):
        slides = [
            {"id": 1, "slide_number": 1, "section_index": 1, "title": "A", "slide_text": "内容 A"},
            {"id": 2, "slide_number": 2, "section_index": 2, "title": "B", "slide_text": "内容 B"},
        ]
        sections = [
            {"section_index": 1, "title": "第一块", "start_slide": 1, "end_slide": 1},
            {"section_index": 2, "title": "第二块", "start_slide": 2, "end_slide": 2},
        ]

        batches = ppt_tutor._build_study_asset_batches(
            slides,
            sections=sections,
            max_chars=8000,
            include_ai_explanation=False,
            split_by_sections=True,
            fallback_range_label="全部目录块",
        )

        self.assertEqual(len(batches), 2)
        self.assertIn("第一块", batches[0]["range_label"])
        self.assertIn("第二块", batches[1]["range_label"])
        self.assertEqual([batch["used_pages"] for batch in batches], [1, 1])

    def test_merge_study_asset_batches_keeps_cards_from_each_batch(self):
        batch_results = [
            {
                "batch": {"range_label": "目录块 1", "used_pages": 2, "truncated": False},
                "assets": {
                    "study_session": {
                        "summary": "第一块总结",
                        "mastered_content": "会 A",
                        "blockers": "卡 A",
                        "wrong_questions": "问 A",
                        "mastery": 60,
                    },
                    "knowledge_cards": [{"subject": "数学", "topic": "A", "one_sentence": "A"}],
                },
            },
            {
                "batch": {"range_label": "目录块 2", "used_pages": 2, "truncated": False},
                "assets": {
                    "study_session": {
                        "summary": "第二块总结",
                        "mastered_content": "会 B",
                        "blockers": "卡 B",
                        "wrong_questions": "问 B",
                        "mastery": 55,
                    },
                    "knowledge_cards": [{"subject": "数学", "topic": "B", "one_sentence": "B"}],
                },
            },
        ]

        merged = ppt_tutor._merge_study_asset_batches(
            batch_results,
            deck={"title": "讲义", "subject": "数学"},
            range_label="全部目录块",
        )

        self.assertEqual(len(merged["knowledge_cards"]), 2)
        self.assertEqual(merged["study_session"]["mastery"], 55)
        self.assertIn("目录块 1：第一块总结", merged["study_session"]["summary"])
        self.assertIn("目录块 2：第二块总结", merged["study_session"]["summary"])

    def test_coverage_report_marks_missing_cards(self):
        batches = [
            {"range_label": "目录块 1", "used_pages": 2, "truncated": False},
            {"range_label": "目录块 2", "used_pages": 3, "truncated": True},
        ]
        batch_results = [
            {
                "batch": batches[0],
                "assets": {"knowledge_cards": [{"topic": "A"}]},
            }
        ]

        report = ppt_tutor._build_study_asset_coverage_report(batch_results, batches)

        self.assertEqual(report[0]["状态"], "已覆盖")
        self.assertEqual(report[1]["状态"], "需补充")
        self.assertEqual(report[1]["截断"], "是")

    def test_background_study_asset_worker_generates_draft(self):
        task = {
            "status": "running",
            "progress": 0.0,
            "range_label": "全部目录块",
            "batches": [
                {
                    "range_label": "目录块 1",
                    "reading_content": "内容 A",
                    "used_pages": 2,
                    "truncated": False,
                    "slide_numbers": [1, 2],
                },
                {
                    "range_label": "目录块 2",
                    "reading_content": "内容 B",
                    "used_pages": 1,
                    "truncated": False,
                    "slide_numbers": [5],
                },
            ],
            "provider_key": "provider-a",
            "api_key": "sk-test",
            "active_model": "model-a",
            "max_tokens": 2048,
            "reasoning_depth": "low",
        }
        deck = {"title": "讲义", "subject": "数学"}
        outputs = [
            """
            {
              "study_session": {"summary": "第一块", "mastery": 70},
              "knowledge_cards": [{"subject": "数学", "topic": "A", "one_sentence": "A"}]
            }
            """,
            """
            {
              "study_session": {"summary": "第二块", "mastery": 65},
              "knowledge_cards": [{"subject": "数学", "topic": "B", "one_sentence": "B"}]
            }
            """,
        ]

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=outputs) as generate_text,
            patch.object(ppt_tutor, "render_template", side_effect=lambda _name, context: context["reading_content"]),
        ):
            ppt_tutor._background_study_asset_worker(task, deck)

        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress"], 1.0)
        self.assertEqual(task["completed_batches"], 2)
        self.assertEqual(len(task["raw_outputs"]), 2)
        self.assertEqual(len(task["draft"]["knowledge_cards"]), 2)
        self.assertEqual(task["meta"]["slide_numbers"], [1, 2, 5])
        self.assertEqual(task["draft"]["study_session"]["mastery"], 65)
        self.assertEqual(generate_text.call_count, 2)

    def test_background_study_asset_worker_retries_timeout_batch(self):
        task = {
            "status": "running",
            "progress": 0.0,
            "range_label": "全部目录块",
            "batches": [
                {
                    "range_label": "目录块 1",
                    "reading_content": "内容 A",
                    "used_pages": 2,
                    "truncated": False,
                }
            ],
            "provider_key": "provider-a",
            "api_key": "sk-test",
            "active_model": "model-a",
            "max_tokens": 2048,
            "reasoning_depth": "low",
        }
        deck = {"title": "讲义", "subject": "数学"}
        calls = []

        def fake_generate_text(*_args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise AIServiceError(
                    "API 请求失败：HTTPConnectionPool(host='localhost', port=8317): Read timed out. (read timeout=120)",
                    category="timeout",
                )
            return """
            {
              "study_session": {"summary": "重试成功", "mastery": 72},
              "knowledge_cards": [{"subject": "数学", "topic": "A", "one_sentence": "A"}]
            }
            """

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "render_template", side_effect=lambda _name, context: context["reading_content"]),
            patch.object(ppt_tutor.time, "sleep") as sleep,
        ):
            ppt_tutor._background_study_asset_worker(task, deck)

        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["completed_batches"], 1)
        self.assertEqual(task["retried"], 1)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call["request_timeout"] == ppt_tutor.PPT_STUDY_ASSET_REQUEST_TIMEOUT_SECONDS for call in calls))
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
