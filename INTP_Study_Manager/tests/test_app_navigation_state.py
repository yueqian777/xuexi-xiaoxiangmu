import unittest

import app


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
        self.assertEqual(entries_by_section["today"], ["dashboard"])
        self.assertEqual(
            entries_by_section["materials"],
            ["ppt_tutor", "ppt_management", "ppt_explanation_import", "ppt_explanation_export"],
        )
        self.assertEqual(
            entries_by_section["knowledge"],
            ["study_sessions", "knowledge_cards", "mainline_branches", "parking_lot"],
        )
        self.assertEqual(entries_by_section["review"], ["reviews", "quiz_prompts", "mistakes"])
        self.assertEqual(entries_by_section["maintenance"], ["api_settings", "markdown_export", "reminders"])

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


if __name__ == "__main__":
    unittest.main()
