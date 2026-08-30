import unittest
from pathlib import Path
from unittest.mock import patch

import app
from pages import chatgpt_web_explanation


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


class ChatGptWebExplanationUiTest(unittest.TestCase):
    def test_navigation_registers_bridge_under_materials(self):
        entry = next(item for item in app.NAV_ENTRIES if item.id == "chatgpt_web_explanation")

        self.assertEqual(entry.label, "ChatGPT 网页讲解")
        self.assertEqual(entry.section_id, "materials")
        self.assertEqual(app._normalize_page_id("ChatGPT 网页讲解"), "chatgpt_web_explanation")

    def test_page_exposes_create_inbox_and_manual_upload_sections(self):
        source = _source("pages/chatgpt_web_explanation.py")

        for text in [
            "创建 ChatGPT 讲解任务",
            "Inbox 自动发现",
            "手动上传 explanation_result.json",
            "当前目录块",
            "自定义页码",
            "全部 PPT",
        ]:
            self.assertIn(text, source)

    def test_page_has_zip_download_scan_preview_and_default_manual_confirmation(self):
        source = _source("pages/chatgpt_web_explanation.py")

        self.assertIn(".download_button(", source)
        self.assertIn('mime="application/zip"', source)
        self.assertIn("st.file_uploader", source)
        self.assertIn('type=["json"]', source)
        self.assertIn("立即扫描 Inbox", source)
        self.assertIn("等待确认", source)
        self.assertIn("完整校验通过后自动导入", source)
        self.assertIn("导入有效", source)

    def test_ppt_tutor_has_lightweight_bridge_shortcut_and_navigation_intent(self):
        source = _source("pages/ppt_tutor.py")

        self.assertIn("生成 ChatGPT 网页精讲任务", source)
        self.assertIn("chatgpt_web_explanation_nav_intent", source)
        self.assertIn('set_navigation_target("materials", "chatgpt_web_explanation")', source)
        self.assertIn("st.rerun()", source)
        self.assertRegex(
            source,
            r'elif workbench_mode == "生成讲解":\s+_render_chatgpt_web_bridge_shortcut\(',
        )

    def test_manual_import_reports_archive_failure_without_false_success(self):
        outcome = {
            "status": "imported",
            "imported_count": 2,
            "deck_id": 1,
            "result_id": "result-ui",
            "archive_status": "failed",
            "archive_error": "file is locked",
        }

        with patch.object(chatgpt_web_explanation, "st") as mocked_st:
            mocked_st.button.return_value = False
            chatgpt_web_explanation._render_import_success(outcome)

        mocked_st.success.assert_not_called()
        self.assertIn("尚未成功归档", mocked_st.warning.call_args.args[0])
        mocked_st.error.assert_called_once_with("file is locked")

    def test_auto_import_reports_archive_failure_without_false_success(self):
        item = {
            "path": "result.json",
            "status": "imported",
            "import": {
                "status": "imported",
                "archive_status": "failed",
                "archive_error": "move failed",
            },
        }

        with patch.object(chatgpt_web_explanation, "st") as mocked_st:
            chatgpt_web_explanation._render_inbox_item(1, item)

        mocked_st.success.assert_not_called()
        self.assertIn("尚未成功归档", mocked_st.warning.call_args.args[0])
        mocked_st.error.assert_called_once_with("move failed")

    def test_imported_but_unarchived_result_offers_safe_archive_retry(self):
        item = {
            "path": "result.json",
            "status": "already_imported",
            "report": {"existing_source_path": "result.json"},
        }
        retry_outcome = {
            "status": "skipped",
            "archive_status": "archived",
            "result_id": "result-ui",
        }

        with (
            patch.object(chatgpt_web_explanation, "st") as mocked_st,
            patch.object(
                chatgpt_web_explanation.inbox_service,
                "import_inbox_result",
                return_value=retry_outcome,
            ) as retry_import,
        ):
            mocked_st.button.return_value = True
            chatgpt_web_explanation._render_inbox_item(1, item)

        retry_import.assert_called_once()
        self.assertIn("尚未完成归档", mocked_st.warning.call_args.args[0])
        self.assertIn("未重复写库", mocked_st.success.call_args.args[0])

    def test_invalid_or_cross_user_result_does_not_render_payload_preview(self):
        report = {
            "hard_valid": False,
            "duplicate_payload_matches": False,
            "errors": ["task_id 不属于当前用户"],
            "warnings": [],
            "payload": {
                "task_id": "another-user-task",
                "slides": [{"explanation": "private explanation"}],
            },
        }

        with patch.object(chatgpt_web_explanation, "st") as mocked_st:
            chatgpt_web_explanation._render_validation_report(report)

        mocked_st.json.assert_not_called()
        mocked_st.markdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
