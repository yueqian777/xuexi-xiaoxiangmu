import unittest
from unittest.mock import patch

from services import reminder_service


class ReminderServiceTest(unittest.TestCase):
    def test_windows_status_returns_cleanly_on_non_windows(self):
        with patch.object(reminder_service.platform, "system", return_value="Linux"):
            ok, output = reminder_service.get_windows_task_status()

        self.assertFalse(ok)
        self.assertTrue(output)

    def test_missing_task_detection_covers_powershell_and_schtasks(self):
        self.assertTrue(reminder_service._looks_like_missing_task("No MSFT_ScheduledTask objects found"))
        self.assertTrue(reminder_service._looks_like_missing_task("ERROR: The system cannot find the file specified."))


if __name__ == "__main__":
    unittest.main()
