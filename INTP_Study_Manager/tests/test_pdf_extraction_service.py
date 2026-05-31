import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from services.pdf_extraction_service import (
    MinerUStatus,
    extract_pdf_pages,
    get_mineru_status,
    parse_mineru_content_list,
)


class FakePdfPlumberPage:
    def __init__(self, text):
        self._text = text
        self.closed = False

    def extract_text(self, **_kwargs):
        return self._text

    def extract_table(self, **_kwargs):
        return [["A", "B"], ["1", "2"]]

    def close(self):
        self.closed = True


class FakePdfPlumberDocument:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class PdfExtractionServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.pdf_path = Path(self.tmp.name) / "deck.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 fake")

    def test_local_extraction_uses_pdfplumber_page_text_and_table_markdown(self):
        fake_pdfplumber = types.SimpleNamespace(
            open=lambda _path: FakePdfPlumberDocument([FakePdfPlumberPage("Header\nBody")])
        )
        fake_pypdf = types.SimpleNamespace(
            PdfReader=lambda _path: types.SimpleNamespace(
                pages=[types.SimpleNamespace(extract_text=lambda: "pypdf fallback")]
            )
        )

        with patch.dict("sys.modules", {"pdfplumber": fake_pdfplumber, "pypdf": fake_pypdf}):
            pages = extract_pdf_pages(self.pdf_path, method="local")

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["slide_number"], 1)
        self.assertEqual(pages[0]["title"], "Header")
        self.assertIn("Header", pages[0]["slide_text"])
        self.assertIn("| A | B |", pages[0]["slide_text"])
        self.assertIn("source=pdf;extractor=local:pdfplumber", pages[0]["notes"])

    def test_local_extraction_falls_back_to_fitz_when_text_extractors_are_empty(self):
        class FakeFitzPage:
            def get_text(self, _mode):
                return "Fitz fallback text"

        class FakeFitzDocument:
            def __iter__(self):
                return iter([FakeFitzPage()])

            def close(self):
                pass

        fake_pypdf = types.SimpleNamespace(
            PdfReader=lambda _path: types.SimpleNamespace(
                pages=[types.SimpleNamespace(extract_text=lambda: "")]
            )
        )
        fake_fitz = types.SimpleNamespace(open=lambda _path: FakeFitzDocument())

        with patch.dict("sys.modules", {"pypdf": fake_pypdf, "fitz": fake_fitz}):
            pages = extract_pdf_pages(self.pdf_path, method="local")

        self.assertEqual(pages[0]["slide_text"], "Fitz fallback text")
        self.assertIn("extractor=local:fitz", pages[0]["notes"])

    def test_parse_mineru_content_list_groups_blocks_by_page(self):
        content = [
            {"type": "text", "text": "Chapter 1", "text_level": 1, "page_idx": 0},
            {"type": "equation", "text": "$$x = y + 1$$", "page_idx": 0},
            {
                "type": "table",
                "table_caption": ["Table 1"],
                "table_body": "<table><tr><td>A</td><td>B</td></tr></table>",
                "page_idx": 1,
            },
        ]
        pages = parse_mineru_content_list(content)

        self.assertEqual([page["slide_number"] for page in pages], [1, 2])
        self.assertEqual(pages[0]["title"], "Chapter 1")
        self.assertIn("$$x = y + 1$$", pages[0]["slide_text"])
        self.assertIn("Table 1", pages[1]["slide_text"])
        self.assertIn("<table>", pages[1]["slide_text"])
        self.assertIn("extractor=mineru", pages[0]["notes"])

    def test_parse_mineru_content_list_v2_nested_pages(self):
        content = [
            [
                {
                    "type": "title",
                    "content": {
                        "title_content": [{"type": "text", "content": "Nested Title"}],
                        "level": 1,
                    },
                },
                {
                    "type": "paragraph",
                    "content": {
                        "paragraph_content": [{"type": "text", "content": "Nested body"}]
                    },
                },
            ]
        ]
        pages = parse_mineru_content_list(content)

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["title"], "Nested Title")
        self.assertIn("Nested body", pages[0]["slide_text"])

    def test_mineru_status_requires_configured_command_to_exist(self):
        with patch.dict("os.environ", {"INTP_MINERU_COMMAND": str(Path(self.tmp.name) / "missing.exe")}, clear=False):
            status = get_mineru_status()

        self.assertFalse(status.available)
        self.assertIn("INTP_MINERU_COMMAND", status.message)

    def test_mineru_status_accepts_existing_configured_command(self):
        command = Path(self.tmp.name) / "mineru.exe"
        command.write_text("", encoding="utf-8")

        with (
            patch.dict("os.environ", {"INTP_MINERU_COMMAND": str(command)}, clear=False),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "MinerU 3.2.1")),
        ):
            status = get_mineru_status()

        self.assertTrue(status.available)
        self.assertEqual(status.command, str(command))

    def test_mineru_status_rejects_existing_command_when_probe_fails(self):
        command = Path(self.tmp.name) / "mineru.exe"
        command.write_text("", encoding="utf-8")

        with (
            patch.dict("os.environ", {"INTP_MINERU_COMMAND": str(command)}, clear=False),
            patch(
                "services.pdf_extraction_service._probe_mineru_command",
                return_value=(False, "ModuleNotFoundError: No module named 'six'"),
            ),
        ):
            status = get_mineru_status()

        self.assertFalse(status.available)
        self.assertEqual(status.command, str(command))
        self.assertIn("无法运行", status.message)
        self.assertIn("six", status.message)


if __name__ == "__main__":
    unittest.main()
