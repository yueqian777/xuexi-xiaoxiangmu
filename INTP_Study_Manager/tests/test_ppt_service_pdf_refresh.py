import types
import unittest
from unittest.mock import patch

from services import ppt_service


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_args):
        return False


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.executemany_calls = []

    def execute(self, query, params=()):
        self.executed.append((query, tuple(params)))

    def executemany(self, query, params_seq):
        rows = [tuple(params) for params in params_seq]
        self.executemany_calls.append((query, rows))


class PptServicePdfRefreshTest(unittest.TestCase):
    def test_refresh_pdf_slide_text_inserts_extracted_pages_missing_from_existing_rows(self):
        conn = FakeConnection()
        deck = {"id": 5, "file_path": "deck.pdf"}
        slides = [
            {"id": 11, "user_id": 7, "deck_id": 5, "slide_number": 1},
        ]
        extracted = [
            {"slide_number": 1, "title": "Page 1", "slide_text": "Updated text", "notes": "source=pdf"},
            {"slide_number": 3, "title": "Page 3", "slide_text": "Inserted text", "notes": "source=pdf"},
        ]

        with (
            patch.object(ppt_service, "require_login", return_value=types.SimpleNamespace(id=7)),
            patch.object(ppt_service, "extract_pdf_pages", return_value=extracted),
            patch.object(ppt_service, "write_transaction", return_value=FakeTransaction(conn)),
        ):
            updated = ppt_service.refresh_pdf_slide_text(deck, slides, method="mineru")

        self.assertEqual(updated, 2)
        update_query, update_rows = conn.executemany_calls[0]
        self.assertIn("UPDATE ppt_slides", update_query)
        self.assertEqual(update_rows[0], ("Page 1", "Updated text", "source=pdf", 11, 7))
        insert_query, insert_rows = conn.executemany_calls[1]
        self.assertIn("INSERT OR IGNORE INTO ppt_slides", insert_query)
        self.assertEqual(insert_rows[0], (7, 5, 3, "Page 3", "Inserted text", "source=pdf", ""))
        self.assertIn(("UPDATE ppt_decks SET slide_count = CASE WHEN slide_count < ? THEN ? ELSE slide_count END WHERE id = ? AND user_id = ?", (3, 3, 5, 7)), conn.executed)


if __name__ == "__main__":
    unittest.main()
