import unittest

from services.ppt_generation_state import apply_stop_request, generation_progress_patch


class PptGenerationStateTest(unittest.TestCase):
    def test_apply_stop_request_stops_running_task(self):
        task = {"status": "running", "stop_requested": True}

        self.assertEqual(apply_stop_request(task, default_status_text="已停止"), "stopped")
        self.assertEqual(task["status"], "stopped")
        self.assertEqual(task["status_text"], "已停止")

    def test_apply_stop_request_keeps_existing_status_text(self):
        task = {"status": "running", "stop_requested": True, "status_text": "用户停止"}

        apply_stop_request(task, default_status_text="已停止")

        self.assertEqual(task["status_text"], "用户停止")

    def test_apply_stop_request_leaves_non_running_task(self):
        task = {"status": "completed", "stop_requested": True}

        self.assertEqual(apply_stop_request(task, default_status_text="已停止"), "completed")
        self.assertEqual(task["status"], "completed")

    def test_generation_progress_patch_uses_message_first(self):
        patch = generation_progress_patch(
            processed=1,
            total=4,
            generated=1,
            skipped=0,
            failed=0,
            inflight=[2, 3],
            message="第 1 页完成",
        )

        self.assertEqual(patch["progress"], 0.25)
        self.assertEqual(patch["status_text"], "第 1 页完成")

    def test_generation_progress_patch_formats_inflight_pages(self):
        patch = generation_progress_patch(
            processed=2,
            total=8,
            generated=2,
            skipped=0,
            failed=0,
            inflight=[3, 4, 5, 6, 7],
        )

        self.assertEqual(patch["status_text"], "正在并行分析第 3、4、5、6... 页；已完成 2 / 8 页。")

    def test_generation_progress_patch_handles_zero_total(self):
        patch = generation_progress_patch(
            processed=0,
            total=0,
            generated=0,
            skipped=0,
            failed=0,
            inflight=[],
        )

        self.assertEqual(patch["progress"], 1.0)
        self.assertEqual(patch["status_text"], "已完成 0 / 0 页。")


if __name__ == "__main__":
    unittest.main()
