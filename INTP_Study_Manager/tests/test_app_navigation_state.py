import unittest

import app


class AppNavigationStateTest(unittest.TestCase):
    def test_mark_active_page_detects_first_entry_and_same_page_refresh(self):
        state = {}

        self.assertTrue(app._mark_active_page("PPT 逐页讲解", state))
        self.assertEqual(state[app.ACTIVE_PAGE_STATE_KEY], "PPT 逐页讲解")
        self.assertTrue(state[app.PAGE_JUST_ENTERED_STATE_KEY])

        self.assertFalse(app._mark_active_page("PPT 逐页讲解", state))
        self.assertFalse(state[app.PAGE_JUST_ENTERED_STATE_KEY])

    def test_mark_active_page_detects_navigation_between_pages(self):
        state = {app.ACTIVE_PAGE_STATE_KEY: "首页 Dashboard"}

        self.assertTrue(app._mark_active_page("PPT 逐页讲解", state))
        self.assertEqual(state[app.ACTIVE_PAGE_STATE_KEY], "PPT 逐页讲解")
        self.assertTrue(state[app.PAGE_JUST_ENTERED_STATE_KEY])


if __name__ == "__main__":
    unittest.main()
