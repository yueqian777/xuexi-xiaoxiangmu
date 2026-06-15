import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from services import ppt_animation_service


class PptAnimationServiceTest(unittest.TestCase):
    def test_sample_animation_states_keeps_first_last_and_evenly_spaced(self):
        states = [
            {
                "slide_number": 1,
                "state_index": index,
                "relative_path": f"slide_001/state_{index:03d}.png",
            }
            for index in range(35)
        ]

        sampled = ppt_animation_service.sample_animation_states(states, max_states=30)

        self.assertEqual(len(sampled), 30)
        self.assertEqual(sampled[0]["state_index"], 0)
        self.assertEqual(sampled[-1]["state_index"], 34)
        self.assertTrue(all(item.get("sampled") for item in sampled))

    def test_generate_deck_animation_states_replaces_rows_from_manifest(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            source = Path(temp_dir) / "deck.pptx"
            source.write_bytes(b"pptx")
            output_root = Path(temp_dir) / "animations"

            def capture(_ppt_path, target_dir):
                image = Path(target_dir) / "slide_001" / "state_000.png"
                image.parent.mkdir(parents=True)
                image.write_bytes(b"png")
                return [
                    {
                        "slide_number": 1,
                        "state_index": 0,
                        "relative_path": "slide_001/state_000.png",
                        "label": "初始",
                        "step_summary": "初始状态",
                    }
                ]

            deck = {"id": 5, "user_id": 7, "file_path": str(source)}
            slides = [{"id": 101, "slide_number": 1, "image_path": "static.png"}]

            with patch.object(ppt_animation_service, "PAGE_ANIMATION_DIR", output_root), patch.object(
                ppt_animation_service.ppt_repository, "replace_slide_animation_states", return_value=1
            ) as replace:
                result = ppt_animation_service.generate_deck_animation_states(
                    deck,
                    slides,
                    capture_func=capture,
                    user=types.SimpleNamespace(id=7),
                )

        self.assertFalse(result.skipped_reason)
        self.assertEqual(result.generated_by_slide, {1: 1})
        args = replace.call_args.args
        self.assertEqual(args[:4], (7, 5, 101, 1))
        self.assertTrue(args[4][0]["image_path"].endswith("slide_001\\state_000.png") or args[4][0]["image_path"].endswith("slide_001/state_000.png"))

    def test_generate_deck_animation_states_does_not_clear_rows_when_capture_fails(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            source = Path(temp_dir) / "deck.pptx"
            source.write_bytes(b"pptx")
            static_image = Path(temp_dir) / "page.png"
            static_image.write_bytes(b"static")

            def capture(_ppt_path, _target_dir):
                raise RuntimeError("PowerPoint failed")

            deck = {"id": 5, "user_id": 7, "file_path": str(source)}
            slides = [{"id": 101, "slide_number": 1, "image_path": str(static_image)}]

            with patch.object(ppt_animation_service, "PAGE_ANIMATION_DIR", Path(temp_dir) / "animations"), patch.object(
                ppt_animation_service.ppt_repository, "replace_slide_animation_states"
            ) as replace:
                result = ppt_animation_service.generate_deck_animation_states(
                    deck,
                    slides,
                    capture_func=capture,
                    user=types.SimpleNamespace(id=7),
                )

            self.assertTrue(static_image.exists())

        self.assertIn("PowerPoint failed", result.skipped_reason)
        replace.assert_not_called()

    def test_generate_deck_animation_states_skips_non_pptx_sources(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            source = Path(temp_dir) / "deck.pdf"
            source.write_bytes(b"pdf")
            result = ppt_animation_service.generate_deck_animation_states(
                {"id": 5, "user_id": 7, "file_path": str(source)},
                [{"id": 101, "slide_number": 1}],
                capture_func=lambda _ppt, _target: [],
                user=types.SimpleNamespace(id=7),
            )

        self.assertEqual(result.generated_by_slide, {})
        self.assertIn("PPTX", result.skipped_reason)


if __name__ == "__main__":
    unittest.main()
