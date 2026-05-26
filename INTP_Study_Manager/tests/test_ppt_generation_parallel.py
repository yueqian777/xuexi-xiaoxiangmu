import time
import unittest
from unittest.mock import patch

from pages import ppt_tutor


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _FakeStreamlit:
    def __init__(self, task):
        self.session_state = {"ppt_generation_task": task}
        self.rerun_called = False

    def success(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def progress(self, *args, **kwargs):
        pass

    def caption(self, *args, **kwargs):
        pass

    def columns(self, *args, **kwargs):
        return [_Context(), _Context()]

    def button(self, *args, **kwargs):
        return False

    def rerun(self):
        self.rerun_called = True


class PptGenerationParallelTest(unittest.TestCase):
    def test_generation_parallelism_is_clamped_to_safe_target_count(self):
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(None, 10), 1)
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(0, 10), 1)
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(3, 2), 2)
        self.assertEqual(ppt_tutor._normalize_generation_parallelism(99, 20), 4)

    def test_running_generation_status_does_not_block_page_render(self):
        task = {
            "status": "running",
            "progress": 0.25,
            "status_text": "正在分析第 2 页...",
            "generated": 1,
            "skipped": 0,
            "failed": 0,
            "parallelism": 2,
        }
        fake_st = _FakeStreamlit(task)

        with patch.object(ppt_tutor, "st", fake_st):
            returned = ppt_tutor._resume_interrupted_generation()

        self.assertIs(returned, task)
        self.assertFalse(fake_st.rerun_called)

    def test_background_generation_worker_runs_slide_requests_in_parallel(self):
        task = {
            "status": "running",
            "progress": 0.0,
            "status_text": "",
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "parallelism": 2,
            "send_image_when_no_text": False,
            "force_image_input": False,
            "supports_image_input": False,
            "provider_key": "test-provider",
            "api_key": "test-key",
            "active_model": "test-model",
            "max_tokens": 100,
            "active_model_label": "测试模型",
            "reasoning_depth": "关闭",
            "context_by_slide": {},
            "related_knowledge": "",
            "user_id": 7,
            "stop_requested": False,
        }
        slides = [
            {"id": 1, "slide_number": 1, "title": "A", "slide_text": "text"},
            {"id": 2, "slide_number": 2, "title": "B", "slide_text": "text"},
            {"id": 3, "slide_number": 3, "title": "C", "slide_text": "text"},
        ]
        active_calls = 0
        max_active_calls = 0

        def fake_generate_text(prompt, **kwargs):
            nonlocal active_calls, max_active_calls
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            time.sleep(0.05)
            active_calls -= 1
            return f"讲解：{prompt}"

        with (
            patch.object(ppt_tutor, "generate_text", side_effect=fake_generate_text),
            patch.object(ppt_tutor, "insert_and_get_id", return_value=1) as insert_and_get_id,
            patch.object(ppt_tutor, "_build_slide_prompt", side_effect=lambda deck, slide, **kwargs: f"slide-{slide['slide_number']}"),
            patch.object(ppt_tutor, "_image_paths_for_generation", return_value=[]),
            patch.object(ppt_tutor, "_is_text_empty", return_value=False),
            patch.object(ppt_tutor, "should_use_lightweight_explanation", return_value=False),
        ):
            ppt_tutor._background_generation_worker(task, {"id": 9, "title": "Deck"}, slides)

        self.assertEqual(max_active_calls, 2)
        self.assertEqual(insert_and_get_id.call_count, 3)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["generated"], 3)


if __name__ == "__main__":
    unittest.main()
