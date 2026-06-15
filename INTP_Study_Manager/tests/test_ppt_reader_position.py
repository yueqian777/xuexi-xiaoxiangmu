import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pages import ppt_tutor
from services import ppt_reader_state


class PptReaderPositionTest(unittest.TestCase):
    def test_read_last_reader_position_accepts_positive_ids(self):
        payload = json.dumps({"deck_id": "7", "slide_number": "12"})
        with patch.object(ppt_tutor, "fetch_one", return_value={"value": payload}):
            self.assertEqual(
                ppt_tutor._read_last_reader_position(42),
                {"deck_id": 7, "slide_number": 12},
            )

    def test_read_last_reader_position_ignores_bad_json(self):
        with patch.object(ppt_tutor, "fetch_one", return_value={"value": "not-json"}):
            self.assertEqual(ppt_tutor._read_last_reader_position(42), {})

    def test_parse_reader_position_filters_invalid_values(self):
        payload = json.dumps({"deck_id": "-7", "slide_number": "abc", "ignored": 3})

        self.assertEqual(ppt_reader_state.parse_reader_position(payload), {})

    def test_build_reader_position_payload_reuses_slide_for_same_deck(self):
        self.assertEqual(
            ppt_reader_state.build_reader_position_payload(3, existing={"deck_id": 3, "slide_number": 9}),
            {"deck_id": 3, "slide_number": 9},
        )

    def test_build_reader_position_payload_does_not_reuse_slide_for_new_deck(self):
        self.assertEqual(
            ppt_reader_state.build_reader_position_payload(4, existing={"deck_id": 3, "slide_number": 9}),
            {"deck_id": 4},
        )

    def test_default_reader_deck_id_prefers_session_when_no_valid_memory(self):
        self.assertEqual(
            ppt_reader_state.default_reader_deck_id([2, 4], {"deck_id": 99}, "4"),
            4,
        )

    def test_reader_image_window_slide_numbers_clips_edges(self):
        slides = [{"slide_number": 1}, {"slide_number": 2}, {"slide_number": 3}, {"slide_number": 4}]

        self.assertEqual(
            ppt_reader_state.reader_image_window_slide_numbers(slides, 1, radius=2),
            {1, 2, 3},
        )

    def test_save_last_reader_position_keeps_slide_for_same_deck(self):
        with (
            patch.object(ppt_tutor, "_read_last_reader_position", return_value={"deck_id": 3, "slide_number": 9}),
            patch.object(ppt_tutor, "execute") as execute,
        ):
            ppt_tutor._save_last_reader_position(42, 3)

        execute.assert_not_called()

    def test_save_last_reader_position_writes_new_deck_without_old_slide(self):
        with (
            patch.object(ppt_tutor, "_read_last_reader_position", return_value={"deck_id": 3, "slide_number": 9}),
            patch.object(ppt_tutor, "execute") as execute,
        ):
            ppt_tutor._save_last_reader_position(42, 4)

        args = execute.call_args.args
        self.assertEqual(json.loads(args[1][2]), {"deck_id": 4})

    def test_save_last_reader_position_reads_existing_position_once(self):
        with (
            patch.object(ppt_tutor, "_read_last_reader_position", return_value={"deck_id": 3, "slide_number": 9}) as read_position,
            patch.object(ppt_tutor, "execute") as execute,
        ):
            ppt_tutor._save_last_reader_position(42, 3)

        read_position.assert_called_once_with(42)
        execute.assert_not_called()

    def test_initial_reader_slide_number_uses_valid_remembered_slide(self):
        slides = [{"slide_number": 1}, {"slide_number": 5}]

        self.assertEqual(
            ppt_tutor._initial_reader_slide_number(2, slides, {"deck_id": 2, "slide_number": 5}),
            5,
        )

    def test_initial_reader_slide_number_falls_back_to_first_slide(self):
        slides = [{"slide_number": 1}, {"slide_number": 5}]

        self.assertEqual(
            ppt_tutor._initial_reader_slide_number(2, slides, {"deck_id": 2, "slide_number": 99}),
            1,
        )

    def test_reader_position_update_does_not_refresh_duplicate_token(self):
        with (
            patch.object(ppt_tutor.st, "session_state", {"ppt_reader_position_last_token_3": "tok"}),
            patch.object(ppt_tutor, "_save_last_reader_position") as save_last_reader_position,
        ):
            changed = ppt_tutor._handle_reader_position_update({"id": 3}, 5, "tok")

        self.assertFalse(changed)
        save_last_reader_position.assert_not_called()

    def test_reader_position_update_does_not_refresh_same_slide(self):
        session_state = {"ppt_reader_active_slide_3": 5}
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 42})()),
            patch.object(ppt_tutor, "_save_last_reader_position") as save_last_reader_position,
        ):
            changed = ppt_tutor._handle_reader_position_update({"id": 3}, 5, "tok")

        self.assertFalse(changed)
        self.assertEqual(session_state["ppt_reader_position_last_token_3"], "tok")
        save_last_reader_position.assert_called_once_with(42, 3, 5)

    def test_reader_position_update_refreshes_new_slide(self):
        session_state = {"ppt_reader_active_slide_3": 4}
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 42})()),
            patch.object(ppt_tutor, "_save_last_reader_position"),
        ):
            changed = ppt_tutor._handle_reader_position_update({"id": 3}, 5, "tok")

        self.assertTrue(changed)
        self.assertEqual(session_state["ppt_reader_active_slide_3"], 5)

    def test_reader_position_update_refreshes_same_slide_when_image_window_expands(self):
        slides = [{"slide_number": number} for number in range(1, 8)]
        session_state = {
            "ppt_reader_active_slide_3": 5,
            "ppt_reader_image_cache_3": {"5": 10.0},
        }
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 42})()),
            patch.object(ppt_tutor, "_save_last_reader_position"),
            patch.object(ppt_tutor.time, "monotonic", return_value=20.0),
        ):
            changed = ppt_tutor._handle_reader_position_update(
                {"id": 3},
                5,
                "tok",
                slides=slides,
                image_window_slide_numbers=[4, 5, 6],
            )

        self.assertTrue(changed)
        self.assertEqual(
            set(session_state["ppt_reader_image_cache_3"]),
            {"4", "5", "6"},
        )

    def test_reader_image_window_cache_caps_explicit_slide_requests(self):
        slides = [{"slide_number": number} for number in range(1, 80)]
        session_state = {
            "ppt_reader_active_slide_3": 40,
            "ppt_reader_image_cache_3": {str(number): float(number) for number in range(1, 20)},
        }
        requested = list(range(20, 70))
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 42})()),
            patch.object(ppt_tutor, "_save_last_reader_position"),
            patch.object(ppt_tutor.time, "monotonic", return_value=100.0),
        ):
            ppt_tutor._handle_reader_position_update(
                {"id": 3},
                40,
                "tok",
                slides=slides,
                image_window_slide_numbers=requested,
            )

        cached = session_state["ppt_reader_image_cache_3"]
        self.assertLessEqual(len(cached), ppt_tutor.READER_IMAGE_CACHE_MAX_SLIDES)
        self.assertTrue(all(not str(value).startswith("data:image") for value in cached.values()))

    def test_reader_image_cache_budget_stays_near_prefetch_window(self):
        self.assertEqual(ppt_tutor.READER_IMAGE_WINDOW_RADIUS, 3)
        self.assertEqual(ppt_tutor.READER_IMAGE_PREFETCH_RADIUS, 3)
        self.assertGreaterEqual(ppt_tutor.READER_IMAGE_CACHE_MAX_SLIDES, 15)
        self.assertGreaterEqual(
            ppt_tutor.READER_IMAGE_CACHE_MAX_SLIDES,
            (ppt_tutor.READER_IMAGE_PREFETCH_RADIUS * 2) + 1,
        )

    def test_reader_image_url_cache_stays_bounded_to_reader_window(self):
        self.assertLessEqual(
            ppt_tutor.READER_IMAGE_URL_CACHE_MAX_SLIDES,
            ppt_tutor.READER_IMAGE_CACHE_MAX_SLIDES * 2,
        )
        self.assertEqual(
            ppt_tutor._cached_reader_image_url.cache_info().maxsize,
            ppt_tutor.READER_IMAGE_URL_CACHE_MAX_SLIDES,
        )

    def test_reader_image_url_uses_component_static_file_instead_of_data_uri(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "page.png"
            image_path.write_bytes(b"png-bytes")
            cache_path = Path(temp_dir) / "component_cache"
            with (
                patch.object(ppt_tutor, "SYNCED_READER_IMAGE_CACHE_PATH", cache_path),
                patch.object(ppt_tutor, "SYNCED_READER_IMAGE_URL_BASE", "_reader_image_cache"),
            ):
                ppt_tutor._cached_reader_image_url.cache_clear()
                url = ppt_tutor._reader_image_url(image_path)

            self.assertTrue(url.startswith("_reader_image_cache/"))
            self.assertIn("?v=", url)
            self.assertFalse(url.startswith("data:image"))
            self.assertEqual(len(list(cache_path.rglob("*.png"))), 1)

    def test_reader_first_payload_image_window_uses_remembered_slide_without_session_state(self):
        deck = {"id": 3, "title": "Deck", "subject": "Subject", "user_id": 42}
        slides = [{"id": number, "slide_number": number} for number in range(1, 8)]
        with (
            patch.object(ppt_tutor.st, "session_state", {}),
            patch.object(ppt_tutor, "_remember_reader_image_window") as remember_window,
            patch.object(ppt_tutor, "_reader_cached_image_slide_numbers", return_value={3}),
            patch.object(ppt_tutor, "_questions_by_slide_ids", return_value={}),
            patch.object(ppt_tutor, "_build_reader_payload", return_value=[]),
            patch.object(ppt_tutor, "_get_synced_reader_component", return_value=None),
        ):
            ppt_tutor._render_synced_reader(
                deck,
                slides,
                {},
                {"deck_id": 3, "slide_number": 3},
                [],
            )

        remember_window.assert_called_once_with(3, slides, 3)

    def test_reader_payload_keeps_session_active_slide_over_remembered_position(self):
        deck = {"id": 3, "title": "Deck", "subject": "Subject", "user_id": 42}
        slides = [{"id": number, "slide_number": number} for number in range(1, 8)]
        component_calls = []

        def fake_component(**kwargs):
            component_calls.append(kwargs)
            return None

        with (
            patch.object(ppt_tutor.st, "session_state", {"ppt_reader_active_slide_3": 2}),
            patch.object(ppt_tutor, "_active_model_label", return_value="model"),
            patch.object(ppt_tutor, "_remember_reader_image_window") as remember_window,
            patch.object(ppt_tutor, "_reader_cached_image_slide_numbers", return_value={2}),
            patch.object(ppt_tutor, "_questions_by_slide_ids", return_value={}),
            patch.object(ppt_tutor, "_build_reader_payload", return_value=[{"slideNumber": 2}]),
            patch.object(ppt_tutor, "_get_synced_reader_component", return_value=fake_component),
        ):
            ppt_tutor._render_synced_reader(
                deck,
                slides,
                {},
                {"deck_id": 3, "slide_number": 5},
                [],
            )

        remember_window.assert_called_once_with(3, slides, 2)
        self.assertEqual(component_calls[0]["initial_slide_number"], 2)

    def test_questions_by_slide_ids_uses_grouped_question_fetch(self):
        question_rows = {
            7: [
                {
                    "id": 10,
                    "question": "root",
                    "quote_text": "",
                    "answer": "answer",
                    "model": "model",
                    "category": "",
                    "status": "open",
                    "sort_order": 1,
                    "root_question_id": 10,
                    "parent_question_id": None,
                    "depth": 0,
                    "quote_source": "slide",
                    "quote_source_question_id": None,
                    "created_at": "today",
                }
            ],
            8: [],
        }
        with (
            patch.object(ppt_tutor, "require_login", return_value=type("User", (), {"id": 42})()),
            patch.object(ppt_tutor, "questions_by_slide_ids", return_value=question_rows) as grouped_fetch,
            patch.object(ppt_tutor, "get_slide_question_tree", side_effect=AssertionError("per-slide tree fetch used")),
        ):
            result = ppt_tutor._questions_by_slide_ids([7, 8])

        grouped_fetch.assert_called_once_with(42, [7, 8])
        self.assertEqual(result[7][0]["question"], "root")
        self.assertEqual(result[8], [])

    def test_reader_position_action_saves_backend_last_position(self):
        session_state = {}
        deck = {"id": 3, "user_id": 42}
        slides = [{"id": 5, "slide_number": 5}]
        payload = {
            "action": "reader_position",
            "deckId": 3,
            "slideNumber": 5,
            "token": "tok",
            "imageWindowSlideNumbers": [4, 5, 6],
            "imageWindowRadius": 1,
        }
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor, "_save_last_reader_position") as save_last_reader_position,
            patch.object(ppt_tutor.st, "rerun") as rerun,
        ):
            ppt_tutor._handle_synced_reader_action(deck, slides, {}, payload, [], user_id=42)

        save_last_reader_position.assert_called_once_with(42, 3, 5)
        rerun.assert_called_once()

    def test_auto_refresh_running_generation_skips_unchanged_recent_task(self):
        session_state = {
            ppt_tutor.PPT_GENERATION_REFRESH_STATE_KEY: {
                "task_key": (3, 1, 1, 0, 0, 0, "处理中"),
                "time": 100.0,
            }
        }
        task = {
            "status": "running",
            "deck_id": 3,
            "processed": 1,
            "generated": 1,
            "skipped": 0,
            "failed": 0,
            "status_text": "处理中",
        }
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor.time, "monotonic", return_value=100.4),
            patch.object(ppt_tutor.st, "rerun") as rerun,
        ):
            ppt_tutor._auto_refresh_running_generation(task)

        rerun.assert_not_called()

    def test_structure_running_refresh_continues_when_progress_recently_unchanged(self):
        session_state = {
            ppt_tutor.PPT_STRUCTURE_REFRESH_STATE_KEY: {
                "task_key": (3, "running", 0, 0, 0, 0, 0, "处理中"),
                "time": 100.0,
            }
        }
        task = {
            "status": "running",
            "deck_id": 3,
            "processed": 0,
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "sections": 0,
            "status_text": "处理中",
        }
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor.time, "monotonic", return_value=100.4),
            patch.object(ppt_tutor.time, "sleep") as sleep,
            patch.object(ppt_tutor.st, "rerun") as rerun,
        ):
            ppt_tutor._auto_refresh_structure_generation(task)

        sleep.assert_called_once()
        rerun.assert_called_once()

    def test_structure_terminal_refreshes_once_when_completion_happens_after_top_check(self):
        task = {
            "status": "completed",
            "deck_id": 3,
            "sections": 4,
            "status_text": "目录分块完成",
        }
        session_state = {"ppt_structure_task": task}
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor.st, "rerun") as rerun,
        ):
            ppt_tutor._auto_refresh_structure_generation(task)

        rerun.assert_called_once()
        self.assertEqual(task.get("_post_render_refreshed_status"), "completed")

        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor.st, "rerun") as rerun,
        ):
            ppt_tutor._auto_refresh_structure_generation(task)

        rerun.assert_not_called()

    def test_should_refresh_task_allows_changed_progress(self):
        session_state = {
            "refresh_key": {
                "task_key": (3, 1, 1, 0, 0, 0, "处理中"),
                "time": 100.0,
            }
        }
        task = {
            "deck_id": 3,
            "processed": 2,
            "generated": 2,
            "skipped": 0,
            "failed": 0,
            "status_text": "处理中",
        }
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor.time, "monotonic", return_value=100.4),
        ):
            self.assertTrue(ppt_tutor._should_refresh_task(task, "refresh_key", interval=1.5))

    def test_should_refresh_task_skips_unchanged_recent_progress(self):
        session_state = {
            "refresh_key": {
                "task_key": (3, 1, 1, 0, 0, 0, "处理中"),
                "time": 100.0,
            }
        }
        task = {
            "deck_id": 3,
            "processed": 1,
            "generated": 1,
            "skipped": 0,
            "failed": 0,
            "status_text": "处理中",
        }
        with (
            patch.object(ppt_tutor.st, "session_state", session_state),
            patch.object(ppt_tutor.time, "monotonic", return_value=100.4),
        ):
            self.assertFalse(ppt_tutor._should_refresh_task(task, "refresh_key", interval=1.5))

    def test_service_should_refresh_task_updates_state_on_change(self):
        session_state = {}
        task = {"deck_id": 3, "processed": 1, "generated": 1, "status_text": "处理中"}

        self.assertTrue(
            ppt_reader_state.should_refresh_task(session_state, task, "refresh_key", interval=1.5, now=100.0)
        )
        self.assertIn("refresh_key", session_state)

    def test_reader_payload_exposes_structure_fields_for_component(self):
        payload = ppt_tutor._build_reader_payload(
            [
                {
                    "id": 10,
                    "slide_number": 3,
                    "title": "ROC",
                    "slide_text": "收敛域",
                    "image_path": "",
                    "section_index": 2,
                    "page_type": "正文页",
                    "one_sentence_summary": "解释 ROC",
                    "slide_role": "承接定义",
                    "key_points": "边界条件",
                }
            ],
            {},
            {10: []},
        )

        self.assertEqual(payload[0]["sectionIndex"], 2)
        self.assertEqual(payload[0]["pageType"], "正文页")
        self.assertEqual(payload[0]["summary"], "解释 ROC")
        self.assertEqual(payload[0]["slideRole"], "承接定义")
        self.assertEqual(payload[0]["keyPoints"], "边界条件")

    def test_reader_payload_includes_lightweight_image_urls_for_available_pages(self):
        slides = [
            {"id": 1, "slide_number": 1, "title": "A", "slide_text": "", "image_path": "a.png"},
            {"id": 2, "slide_number": 2, "title": "B", "slide_text": "", "image_path": "b.png"},
        ]
        with (
            patch.object(ppt_tutor.Path, "exists", return_value=True),
            patch.object(ppt_tutor.Path, "is_file", return_value=True),
            patch.object(ppt_tutor, "_reader_image_url", side_effect=lambda path: f"_reader_image_cache/{path}") as image_url,
        ):
            payload = ppt_tutor._build_reader_payload(
                slides,
                {},
                {},
                image_slide_numbers={2},
            )

        self.assertTrue(payload[0]["imageAvailable"])
        self.assertEqual(payload[0]["image"], "_reader_image_cache/a.png")
        self.assertEqual(payload[1]["image"], "_reader_image_cache/b.png")
        self.assertEqual(image_url.call_count, 2)

    def test_reader_sections_payload_uses_component_key_names(self):
        payload = ppt_tutor._reader_sections_payload(
            [
                {
                    "section_index": 1,
                    "title": "Z 变换基础",
                    "start_slide": 1,
                    "end_slide": 8,
                    "core_question": "为什么需要 Z 变换？",
                    "summary": "从序列到复频域。",
                }
            ]
        )

        self.assertEqual(
            payload[0],
            {
                "sectionIndex": 1,
                "title": "Z 变换基础",
                "startSlide": 1,
                "endSlide": 8,
                "coreQuestion": "为什么需要 Z 变换？",
                "summary": "从序列到复频域。",
            },
        )

    def test_slide_prompt_replaces_context_package_placeholder(self):
        context = {
            "deck_title": "Z 变换",
            "section": {
                "title": "收敛域",
                "start_slide": 3,
                "end_slide": 6,
                "core_question": "ROC 怎么决定系统性质？",
            },
            "slide": {"slide_number": 3, "title": "ROC 定义"},
        }
        with (
            patch.object(ppt_tutor, "_related_knowledge_context", return_value="暂无同科目知识卡片。"),
            patch.object(ppt_tutor, "_image_exists", return_value=False),
        ):
            prompt = ppt_tutor._build_slide_prompt(
                {"title": "Z 变换", "subject": "信号与系统"},
                {"slide_number": 3, "title": "ROC 定义", "slide_text": "ROC 是收敛域。"},
                context=context,
            )

        self.assertNotIn("{context_package}", prompt)
        self.assertIn("当前目录块：收敛域", prompt)
        self.assertIn("ROC 怎么决定系统性质？", prompt)

    def test_slide_prompt_includes_animation_summary_once(self):
        with (
            patch.object(ppt_tutor, "_related_knowledge_context", return_value="暂无同科目知识卡片。"),
            patch.object(ppt_tutor, "_image_exists", return_value=False),
            patch.object(ppt_tutor, "_slide_animation_summary", return_value="第 1 步：出现关键公式"),
        ):
            prompt = ppt_tutor._build_slide_prompt(
                {"title": "Z 变换", "subject": "信号与系统"},
                {"id": 9, "slide_number": 3, "title": "ROC 定义", "slide_text": "ROC 是收敛域。"},
                context={},
                user_id=11,
            )

        self.assertEqual(prompt.count("本页动画过程"), 1)
        self.assertIn("第 1 步：出现关键公式", prompt)

    def test_document_structure_generation_fills_prompt_variables(self):
        captured = {}

        def fake_generate_text(prompt, **kwargs):
            captured["prompt"] = prompt
            return json.dumps(
                {
                    "outline": "大纲",
                    "sections": [
                        {
                            "section_index": 1,
                            "title": "整体",
                            "start_slide": 1,
                            "end_slide": 2,
                        }
                    ],
                },
                ensure_ascii=False,
            )

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "save_deck_structure") as save_deck_structure,
        ):
            ppt_tutor._generate_document_structure(
                {"id": 5, "title": "Z 变换", "subject": "信号与系统"},
                [
                    {"slide_number": 1, "title": "第一页", "slide_text": "内容 A"},
                    {"slide_number": 2, "title": "第二页", "slide_text": "内容 B"},
                ],
                provider_key="test",
                api_key="key",
                active_model="model",
                max_tokens=4096,
                reasoning_depth="关闭",
            )

        self.assertNotIn("{slide_count}", captured["prompt"])
        self.assertNotIn("{page_list}", captured["prompt"])
        self.assertIn("总页数：2", captured["prompt"])
        self.assertIn("第 1 页", captured["prompt"])
        save_deck_structure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
