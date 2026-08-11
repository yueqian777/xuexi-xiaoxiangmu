import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import app
from pages import chatgpt_mcp
from services import mcp_permission_service
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


class ChatGptMcpUiTest(unittest.TestCase):
    def test_navigation_registers_mcp_page_under_maintenance(self):
        entry = next(item for item in app.NAV_ENTRIES if item.id == "chatgpt_mcp")

        self.assertEqual(entry.label, "ChatGPT / MCP")
        self.assertEqual(entry.section_id, "maintenance")
        self.assertEqual(app._normalize_page_id("ChatGPT / MCP"), "chatgpt_mcp")

    def test_page_exposes_status_context_permissions_audit_and_no_delete_tool(self):
        source = _source("pages/chatgpt_mcp.py")

        for text in [
            "MCP Server 状态",
            "当前 Active Context",
            "读取权限",
            "写入权限",
            "最近 MCP 操作",
            "不提供删除接口",
            "复制 MCP 配置",
            "测试 get_current_context",
            "测试 get_current_slide",
        ]:
            self.assertIn(text, source)
        self.assertNotIn("study_delete", source)

    def test_permission_ui_covers_exactly_the_nine_local_permissions(self):
        self.assertEqual(
            set(chatgpt_mcp.PERMISSION_LABELS),
            {
                "read_current_context",
                "read_ppt",
                "read_question_tree",
                "read_knowledge_cards",
                "read_reviews",
                "write_slide_explanation",
                "write_slide_question",
                "write_knowledge_card",
                "write_review",
            },
        )

    def test_stdio_config_is_local_process_only_and_contains_no_secret(self):
        config = json.loads(chatgpt_mcp._stdio_config_text(7))
        server = config["mcpServers"]["intp-study-manager"]

        self.assertEqual(
            server["args"],
            ["-m", "study_mcp.server", "--transport", "stdio", "--user-id", "7"],
        )
        self.assertEqual(Path(server["cwd"]), PROJECT_ROOT)
        serialized = json.dumps(config).lower()
        self.assertNotIn("token", serialized)
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("0.0.0.0", serialized)

    def test_bridge_page_explains_mcp_direct_and_file_fallback_without_false_claim(self):
        source = _source("pages/chatgpt_web_explanation.py")

        self.assertIn("方式 A：ChatGPT MCP 直接模式", source)
        self.assertIn("方式 B：文件桥接模式", source)
        self.assertIn("fallback", source)
        self.assertIn("本页继续提供方式 B", source)
        self.assertNotIn("已连接到网页版 ChatGPT", source)

    def test_mcp_docs_keep_local_server_and_web_connection_separate(self):
        architecture = _source("docs/study_manager_mcp.md")
        connection = _source("docs/chatgpt_mcp_connection.md")

        self.assertIn("python -m study_mcp.server --transport stdio --user-id", architecture)
        self.assertIn("JSON Bridge", architecture)
        self.assertIn("14", architecture)
        self.assertIn("本地 MCP Server", connection)
        self.assertIn("不等于", connection)
        self.assertIn("Secure MCP Tunnel", connection)
        self.assertIn("独立连接层", connection)
        self.assertIn("不实现公网 HTTP", connection)

    def test_streamlit_page_smoke_and_permission_save_flow(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            data_dir = Path(tmp)
            with (
                patch.object(db, "DATA_DIR", data_dir),
                patch.object(db, "DATABASE_PATH", data_dir / "study_manager.db"),
            ):
                db._INITIALIZED_DATABASE_PATH = None
                page = AppTest.from_string(
                    "from pages.chatgpt_mcp import render\nrender()",
                    default_timeout=10,
                ).run()

                self.assertEqual(len(page.exception), 0)
                self.assertEqual(page.title[0].value, "ChatGPT / MCP")
                self.assertEqual(len(page.checkbox), 9)
                self.assertFalse(page.checkbox[4].value)

                page.checkbox[4].set_value(True)
                page.button[0].click()
                page.run()

                self.assertEqual(len(page.exception), 0)
                self.assertTrue(mcp_permission_service.get_permissions(0)["read_reviews"])
        db._INITIALIZED_DATABASE_PATH = None


if __name__ == "__main__":
    unittest.main()
