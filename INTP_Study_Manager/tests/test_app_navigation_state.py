import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import db
from services import ui_helpers
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AppNavigationStateTest(unittest.TestCase):
    def test_navigation_entries_are_grouped_by_learning_flow(self):
        self.assertEqual(
            [section.id for section in app.NAV_SECTIONS],
            ["today", "materials", "knowledge", "review", "maintenance"],
        )
        self.assertEqual(
            [section.label for section in app.NAV_SECTIONS],
            ["今日工作台", "资料学习", "知识沉淀", "复习纠错", "系统维护"],
        )

        entries_by_section = {
            section.id: [entry.id for entry in app.NAV_ENTRIES if entry.section_id == section.id]
            for section in app.NAV_SECTIONS
        }
        self.assertEqual(entries_by_section["today"], ["dashboard", "course_center"])
        self.assertEqual(
            entries_by_section["materials"],
            [
                "ppt_tutor",
                "chatgpt_web_explanation",
                "ppt_management",
                "ppt_explanation_import",
                "ppt_explanation_export",
            ],
        )
        self.assertEqual(
            entries_by_section["knowledge"],
            ["study_sessions", "knowledge_cards", "mainline_branches", "parking_lot"],
        )
        self.assertEqual(entries_by_section["review"], ["reviews", "quiz_prompts", "mistakes"])
        self.assertEqual(
            entries_by_section["maintenance"],
            ["chatgpt_mcp", "api_settings", "markdown_export", "reminders"],
        )

    def test_navigation_entry_ids_are_stable_and_unique(self):
        entry_ids = [entry.id for entry in app.NAV_ENTRIES]
        self.assertEqual(len(entry_ids), len(set(entry_ids)))
        self.assertEqual(app.DEFAULT_PAGE_ID, "dashboard")
        self.assertEqual(app._normalize_page_id("PPT 逐页讲解"), "ppt_tutor")
        self.assertEqual(app._normalize_page_id("ppt_tutor"), "ppt_tutor")

    def test_mark_active_page_detects_first_entry_and_same_page_refresh(self):
        state = {}

        self.assertTrue(app._mark_active_page("ppt_tutor", state))
        self.assertEqual(state[app.ACTIVE_PAGE_STATE_KEY], "ppt_tutor")
        self.assertTrue(state[app.PAGE_JUST_ENTERED_STATE_KEY])

        self.assertFalse(app._mark_active_page("ppt_tutor", state))
        self.assertFalse(state[app.PAGE_JUST_ENTERED_STATE_KEY])

    def test_mark_active_page_detects_navigation_between_pages(self):
        state = {app.ACTIVE_PAGE_STATE_KEY: "dashboard"}

        self.assertTrue(app._mark_active_page("PPT 逐页讲解", state))
        self.assertEqual(state[app.ACTIVE_PAGE_STATE_KEY], "ppt_tutor")
        self.assertTrue(state[app.PAGE_JUST_ENTERED_STATE_KEY])

    def test_pending_navigation_target_is_consumed_and_keeps_exact_page(self):
        state = {
            ui_helpers.PENDING_NAVIGATION_STATE_KEY: {
                "section_id": "knowledge",
                "page_id": "knowledge_cards",
            }
        }

        self.assertTrue(app._apply_pending_navigation_target(state))
        self.assertEqual(state[app.SELECTED_SECTION_STATE_KEY], "knowledge")
        self.assertEqual(state[app.SELECTED_PAGE_STATE_KEY], "knowledge_cards")
        self.assertEqual(state[app.PAGE_SECTION_SYNC_STATE_KEY], "knowledge")
        self.assertNotIn(ui_helpers.PENDING_NAVIGATION_STATE_KEY, state)
        self.assertFalse(app._apply_pending_navigation_target(state))

    def test_pending_navigation_target_rejects_mismatched_section(self):
        state = {
            app.SELECTED_SECTION_STATE_KEY: "today",
            app.SELECTED_PAGE_STATE_KEY: "dashboard",
            ui_helpers.PENDING_NAVIGATION_STATE_KEY: {
                "section_id": "knowledge",
                "page_id": "ppt_tutor",
            },
        }

        self.assertFalse(app._apply_pending_navigation_target(state))
        self.assertEqual(state[app.SELECTED_SECTION_STATE_KEY], "today")
        self.assertEqual(state[app.SELECTED_PAGE_STATE_KEY], "dashboard")
        self.assertNotIn(ui_helpers.PENDING_NAVIGATION_STATE_KEY, state)

    def test_dashboard_knowledge_card_shortcut_has_no_widget_state_exception(self):
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                data_dir = Path(tmp)
                with (
                    patch.object(db, "DATA_DIR", data_dir),
                    patch.object(db, "DATABASE_PATH", data_dir / "study_manager.db"),
                ):
                    db._INITIALIZED_DATABASE_PATH = None
                    page = AppTest.from_file(
                        PROJECT_ROOT / "app.py",
                        default_timeout=20,
                    ).run()

                    self.assertEqual(len(page.exception), 0)

                    next(
                        button
                        for button in page.button
                        if button.label == "整理知识卡片"
                    ).click()
                    page.run()

                    self.assertEqual(
                        len(page.exception),
                        0,
                        [str(item.value) for item in page.exception],
                    )
                    self.assertEqual(
                        page.session_state[app.SELECTED_SECTION_STATE_KEY],
                        "knowledge",
                    )
                    self.assertEqual(
                        page.session_state[app.SELECTED_PAGE_STATE_KEY],
                        "knowledge_cards",
                    )
        finally:
            db._INITIALIZED_DATABASE_PATH = None

    def test_course_center_page_renders_without_streamlit_exception(self):
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                data_dir = Path(tmp)
                with (
                    patch.object(db, "DATA_DIR", data_dir),
                    patch.object(db, "DATABASE_PATH", data_dir / "study_manager.db"),
                ):
                    db._INITIALIZED_DATABASE_PATH = None
                    page = AppTest.from_file(
                        PROJECT_ROOT / "app.py",
                        default_timeout=20,
                    ).run()

                    page.sidebar.radio[1].set_value("course_center")
                    page.run()

                    self.assertEqual(
                        len(page.exception),
                        0,
                        [str(item.value) for item in page.exception],
                    )
                    self.assertIn("课程中心", [item.value for item in page.title])
        finally:
            db._INITIALIZED_DATABASE_PATH = None


if __name__ == "__main__":
    unittest.main()
