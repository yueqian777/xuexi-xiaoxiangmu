import json
import unittest
from unittest.mock import patch

from pages import ppt_tutor


class PptReaderPositionTest(unittest.TestCase):
    def test_read_last_reader_position_accepts_positive_ids(self):
        payload = json.dumps({"deck_id": "7", "slide_number": "12"})
        with patch.object(ppt_tutor, "fetch_one", return_value={"value": payload}):
            self.assertEqual(
                ppt_tutor._read_last_reader_position(),
                {"deck_id": 7, "slide_number": 12},
            )

    def test_read_last_reader_position_ignores_bad_json(self):
        with patch.object(ppt_tutor, "fetch_one", return_value={"value": "not-json"}):
            self.assertEqual(ppt_tutor._read_last_reader_position(), {})

    def test_save_last_reader_position_keeps_slide_for_same_deck(self):
        with (
            patch.object(ppt_tutor, "_read_last_reader_position", return_value={"deck_id": 3, "slide_number": 9}),
            patch.object(ppt_tutor, "execute") as execute,
        ):
            ppt_tutor._save_last_reader_position(3)

        execute.assert_not_called()

    def test_save_last_reader_position_writes_new_deck_without_old_slide(self):
        with (
            patch.object(ppt_tutor, "_read_last_reader_position", return_value={"deck_id": 3, "slide_number": 9}),
            patch.object(ppt_tutor, "execute") as execute,
        ):
            ppt_tutor._save_last_reader_position(4)

        args = execute.call_args.args
        self.assertEqual(json.loads(args[1][1]), {"deck_id": 4})

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


if __name__ == "__main__":
    unittest.main()
