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
            {"type": "equation", "text": r"x = y + 1", "page_idx": 0},
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

    def test_parse_mineru_content_list_wraps_latex_in_text_blocks_for_mathjax(self):
        content = [
            {
                "type": "text",
                "text": r"通带截止频率\Omega _ { p }、通带衰减\delta _ { 1 }",
                "page_idx": 0,
            },
            {
                "type": "text",
                "text": r"H _ { a } ( s ) = \frac { 1 } { s + 1 }",
                "page_idx": 0,
            },
        ]
        pages = parse_mineru_content_list(content)

        self.assertIn(r"通带截止频率$\Omega _ { p }$、通带衰减$\delta _ { 1 }$", pages[0]["slide_text"])
        self.assertIn(r"$$H _ { a } ( s ) = \frac { 1 } { s + 1 }$$", pages[0]["slide_text"])

    def test_parse_mineru_content_list_preserves_existing_math_delimiters(self):
        content = [
            {"type": "equation", "text": "$$x = y + 1$$", "page_idx": 0},
        ]
        pages = parse_mineru_content_list(content)

        self.assertEqual(pages[0]["slide_text"], "$$x = y + 1$$")

    def test_parse_mineru_content_list_imports_header_and_footer_blocks(self):
        content = [
            {"type": "header", "text": "Course Header", "page_idx": 0},
            {"type": "text", "text": "Main body", "page_idx": 0},
            {"type": "footer", "text": "Page Footer", "page_idx": 0},
        ]
        pages = parse_mineru_content_list(content)

        self.assertIn("Course Header", pages[0]["slide_text"])
        self.assertIn("Main body", pages[0]["slide_text"])
        self.assertIn("Page Footer", pages[0]["slide_text"])

    def test_parse_mineru_content_list_imports_unknown_text_bearing_blocks(self):
        content = [
            {
                "type": "discarded_by_old_parser",
                "text": r"\Omega _ { s } = 2\pi f _ { s }",
                "page_idx": 0,
            },
            {
                "type": "custom_caption",
                "content": "Caption text that still belongs on the page",
                "page_idx": 0,
            },
        ]
        pages = parse_mineru_content_list(content)

        self.assertIn(r"$$\Omega _ { s } = 2\pi f _ { s }$$", pages[0]["slide_text"])
        self.assertIn("Caption text that still belongs on the page", pages[0]["slide_text"])

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

    def test_parse_mineru_content_list_v2_wraps_interline_equations_for_mathjax(self):
        content = [
            [
                {
                    "type": "equation_interline",
                    "content": {"math_content": r"\omega _ { p } = \Omega _ { p } / T"},
                },
            ]
        ]
        pages = parse_mineru_content_list(content)

        self.assertEqual(
            pages[0]["slide_text"],
            r"$$\omega _ { p } = \Omega _ { p } / T$$",
        )

    def test_parse_mineru_content_list_v2_imports_page_header_and_footer(self):
        content = [
            [
                {
                    "type": "page_header",
                    "content": {"page_header_content": [{"type": "text", "content": "Header mark"}]},
                },
                {
                    "type": "paragraph",
                    "content": {"paragraph_content": [{"type": "text", "content": "Main body"}]},
                },
                {
                    "type": "page_footer",
                    "content": {"page_footer_content": [{"type": "text", "content": "Footer mark"}]},
                },
            ]
        ]
        pages = parse_mineru_content_list(content)

        self.assertIn("Header mark", pages[0]["slide_text"])
        self.assertIn("Main body", pages[0]["slide_text"])
        self.assertIn("Footer mark", pages[0]["slide_text"])

    def test_parse_mineru_content_list_v2_imports_unknown_text_bearing_blocks(self):
        content = [
            [
                {
                    "type": "custom_math",
                    "content": {"math_latex": r"\omega _ { p } = \Omega _ { p } / T"},
                },
                {
                    "type": "custom_spans",
                    "content": {
                        "spans": [
                            {"type": "text", "content": "Nested"},
                            {"type": "text", "text": " span text"},
                        ]
                    },
                },
            ]
        ]
        pages = parse_mineru_content_list(content)

        self.assertIn(r"$$\omega _ { p } = \Omega _ { p } / T$$", pages[0]["slide_text"])
        self.assertIn("Nested span text", pages[0]["slide_text"])

    def test_mineru_extraction_archives_raw_json_and_markdown_outputs(self):
        temp_root = Path(self.tmp.name) / "mineru-temp"
        content_dir = temp_root / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "Archived output", "page_idx": 0}]),
            encoding="utf-8",
        )
        (content_dir / "doc.md").write_text("# Archived output", encoding="utf-8")
        archive_root = Path(self.tmp.name) / "archive"

        def fake_run(_command, **_kwargs):
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_OUTPUT_DIR": str(archive_root),
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(temp_root)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["title"], "Archived output")
        archived_files = {path.name for path in archive_root.rglob("_raw/**/*") if path.is_file()}
        self.assertIn("doc_content_list.json", archived_files)
        self.assertIn("doc.md", archived_files)

    def test_mineru_extraction_uses_richer_content_list_when_v1_has_more_text(self):
        temp_root = Path(self.tmp.name) / "mineru-temp"
        content_dir = temp_root / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list_v2.json").write_text(
            json.dumps([[{"type": "paragraph", "content": {"paragraph_content": "short"}}]]),
            encoding="utf-8",
        )
        (content_dir / "doc_content_list.json").write_text(
            json.dumps(
                [
                    {"type": "text", "text": "short", "page_idx": 0},
                    {"type": "text", "text": "extra formula", "page_idx": 0},
                    {"type": "equation", "text": r"\Omega _ { s } = 2\pi f _ { s }", "page_idx": 0},
                ]
            ),
            encoding="utf-8",
        )

        def fake_run(_command, **_kwargs):
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "archive"),
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(temp_root)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertIn("extra formula", pages[0]["slide_text"])
        self.assertIn(r"$$\Omega _ { s } = 2\pi f _ { s }$$", pages[0]["slide_text"])

    def test_mineru_command_defaults_to_pipeline_backend_and_gpu_zero(self):
        content_dir = Path(self.tmp.name) / "out" / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "GPU default", "page_idx": 0}]),
            encoding="utf-8",
        )
        captured = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            captured["env"] = _kwargs["env"]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "out"),
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(content_dir.parent)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["title"], "GPU default")
        self.assertIn("-b", captured["command"])
        self.assertIn("pipeline", captured["command"])
        self.assertEqual(captured["env"]["CUDA_VISIBLE_DEVICES"], "0")
        self.assertEqual(captured["env"]["MINERU_DEVICE_MODE"], "cuda")

    def test_mineru_command_uses_configured_backend_and_cuda_visible_devices(self):
        content_dir = Path(self.tmp.name) / "out" / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "Configured backend", "page_idx": 0}]),
            encoding="utf-8",
        )
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["env"] = kwargs["env"]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_BACKEND": "pipeline",
            "INTP_MINERU_CUDA_VISIBLE_DEVICES": "0",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "out"),
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(content_dir.parent)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["title"], "Configured backend")
        self.assertIn("-b", captured["command"])
        self.assertIn("pipeline", captured["command"])
        self.assertEqual(captured["env"]["CUDA_VISIBLE_DEVICES"], "0")
        self.assertEqual(captured["env"]["MINERU_DEVICE_MODE"], "cuda")

    def test_mineru_command_respects_configured_device_mode(self):
        content_dir = Path(self.tmp.name) / "out" / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "Configured device", "page_idx": 0}]),
            encoding="utf-8",
        )
        captured = {}

        def fake_run(_command, **kwargs):
            captured["env"] = kwargs["env"]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_DEVICE_MODE": "cpu",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "out"),
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(content_dir.parent)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["title"], "Configured device")
        self.assertEqual(captured["env"]["MINERU_DEVICE_MODE"], "cpu")

    def test_mineru_command_respects_existing_cuda_visible_devices(self):
        content_dir = Path(self.tmp.name) / "out" / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "Existing CUDA env", "page_idx": 0}]),
            encoding="utf-8",
        )
        captured = {}

        def fake_run(_command, **kwargs):
            captured["env"] = kwargs["env"]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "CUDA_VISIBLE_DEVICES": "1",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "out"),
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(content_dir.parent)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["title"], "Existing CUDA env")
        self.assertEqual(captured["env"]["CUDA_VISIBLE_DEVICES"], "1")

    def test_mineru_command_supports_page_range_formula_and_table_options(self):
        content_dir = Path(self.tmp.name) / "out" / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "Configured options", "page_idx": 0}]),
            encoding="utf-8",
        )
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["env"] = kwargs["env"]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "out"),
            "INTP_MINERU_START_PAGE": "84",
            "INTP_MINERU_END_PAGE": "92",
            "INTP_MINERU_FORMULA": "true",
            "INTP_MINERU_TABLE": "true",
            "INTP_MINERU_IMAGE_ANALYSIS": "false",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(content_dir.parent)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["title"], "Configured options")
        self.assertIn("--start", captured["command"])
        self.assertIn("84", captured["command"])
        self.assertIn("--end", captured["command"])
        self.assertIn("92", captured["command"])
        self.assertIn("--formula", captured["command"])
        self.assertIn("true", captured["command"])
        self.assertIn("--table", captured["command"])
        self.assertIn("--image-analysis", captured["command"])
        self.assertIn("false", captured["command"])

    def test_mineru_extraction_offsets_slide_numbers_when_start_page_is_configured(self):
        content_dir = Path(self.tmp.name) / "out" / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "Page range result", "page_idx": 0}]),
            encoding="utf-8",
        )

        def fake_run(_command, **_kwargs):
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "out"),
            "INTP_MINERU_START_PAGE": "84",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(content_dir.parent)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["slide_number"], 85)
        self.assertEqual(pages[0]["title"], "Page range result")

    def test_mineru_command_defaults_cache_and_temp_to_d_drive(self):
        content_dir = Path(self.tmp.name) / "out" / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "D drive cache", "page_idx": 0}]),
            encoding="utf-8",
        )
        captured = {}

        def fake_run(_command, **kwargs):
            captured["env"] = kwargs["env"]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "out"),
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(content_dir.parent)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["title"], "D drive cache")
        self.assertEqual(captured["env"]["TEMP"], "D:\\MinerU\\tmp")
        self.assertEqual(captured["env"]["TMP"], "D:\\MinerU\\tmp")
        self.assertEqual(captured["env"]["HF_HOME"], "D:\\MinerU\\cache\\huggingface")
        self.assertEqual(captured["env"]["MODELSCOPE_CACHE"], "D:\\MinerU\\cache\\modelscope")
        self.assertEqual(captured["env"]["MINERU_MODEL_SOURCE"], "modelscope")
        self.assertEqual(captured["env"]["MINERU_FORMULA_ENABLE"], "true")
        self.assertEqual(captured["env"]["MINERU_TABLE_ENABLE"], "true")
        self.assertEqual(captured["env"]["MINERU_PROCESSING_WINDOW_SIZE"], "16")
        self.assertEqual(captured["env"]["MINERU_API_MAX_CONCURRENT_REQUESTS"], "1")

    def test_mineru_command_respects_configured_model_source(self):
        content_dir = Path(self.tmp.name) / "out" / "doc"
        content_dir.mkdir(parents=True)
        (content_dir / "doc_content_list.json").write_text(
            json.dumps([{"type": "text", "text": "Configured model source", "page_idx": 0}]),
            encoding="utf-8",
        )
        captured = {}

        def fake_run(_command, **kwargs):
            captured["env"] = kwargs["env"]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        env = {
            "INTP_MINERU_COMMAND": "D:\\MinerU\\.venv\\Scripts\\mineru.exe",
            "INTP_MINERU_OUTPUT_DIR": str(Path(self.tmp.name) / "out"),
            "INTP_MINERU_MODEL_SOURCE": "huggingface",
            "INTP_MINERU_FORMULA": "false",
            "INTP_MINERU_TABLE": "false",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("services.pdf_extraction_service._resolve_command", return_value=env["INTP_MINERU_COMMAND"]),
            patch("services.pdf_extraction_service._probe_mineru_command", return_value=(True, "ok")),
            patch("services.pdf_extraction_service.tempfile.TemporaryDirectory") as temporary_directory,
            patch("services.pdf_extraction_service.subprocess.run", side_effect=fake_run),
        ):
            temporary_directory.return_value.__enter__.return_value = str(content_dir.parent)
            pages = extract_pdf_pages(self.pdf_path, method="mineru")

        self.assertEqual(pages[0]["title"], "Configured model source")
        self.assertEqual(captured["env"]["MINERU_MODEL_SOURCE"], "huggingface")
        self.assertEqual(captured["env"]["MINERU_FORMULA_ENABLE"], "false")
        self.assertEqual(captured["env"]["MINERU_TABLE_ENABLE"], "false")

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
