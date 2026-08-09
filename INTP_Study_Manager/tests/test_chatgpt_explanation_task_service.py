import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import db
from services import chatgpt_explanation_task_service as task_service


class ChatGptExplanationTaskServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()
        self.user_id = 7

    def _seed_deck(self, slide_count=4, *, user_id=None, sections=None):
        owner_id = self.user_id if user_id is None else int(user_id)
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (user_id, filename, title, subject, file_path, slide_count)
            VALUES (?, 'fir.pdf', 'FIR 数字滤波器', '信号与系统', 'fir.pdf', ?)
            """,
            (owner_id, slide_count),
        )
        slide_ids = []
        for number in range(1, slide_count + 1):
            image = self.data_dir / "page_images" / f"slide-{number:03d}.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(f"png-{number}".encode())
            slide_id = db.insert_and_get_id(
                """
                INSERT INTO ppt_slides (
                    user_id, deck_id, slide_number, title, slide_text, image_path,
                    section_index, page_type, one_sentence_summary, slide_role, key_points
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, '公式页', ?, '推导步骤', '理解公式')
                """,
                (
                    owner_id,
                    deck_id,
                    number,
                    f"第 {number} 页",
                    f"公开课件文字 {number}",
                    str(image),
                    1 if number <= max(1, slide_count // 2) else 2,
                    f"摘要 {number}",
                ),
            )
            slide_ids.append(slide_id)
        if sections:
            for index, start, end, title in sections:
                db.insert_and_get_id(
                    """
                    INSERT INTO ppt_sections (
                        user_id, deck_id, section_index, title, topic, core_question,
                        summary, key_terms_json, prerequisite_concepts_json,
                        start_slide, end_slide
                    )
                    VALUES (?, ?, ?, ?, '滤波器', '为什么这样设计？', '目录块摘要',
                            '["频响"]', '["卷积"]', ?, ?)
                    """,
                    (owner_id, deck_id, index, title, start, end),
                )
        first_slide = slide_ids[0]
        db.insert_and_get_id(
            "INSERT INTO slide_explanations (user_id, slide_id, model, explanation) VALUES (?, ?, 'API Model', '旧版私有讲解')",
            (owner_id, first_slide),
        )
        db.insert_and_get_id(
            "INSERT INTO slide_questions (user_id, slide_id, question, answer, model) VALUES (?, ?, '私有插问', '私有回答', 'model')",
            (owner_id, first_slide),
        )
        db.insert_and_get_id(
            "INSERT INTO knowledge_cards (user_id, subject, topic, one_sentence) VALUES (?, '信号与系统', '私有知识卡', '私有复盘')",
            (owner_id,),
        )
        return deck_id, slide_ids

    def test_generate_task_package_for_selected_deck(self):
        deck_id, _ = self._seed_deck(sections=[(1, 1, 4, "第一块")])

        result = task_service.create_task_packages(
            self.user_id,
            deck_id,
            range_mode="section",
            section_index=1,
        )

        self.assertEqual(result["package_count"], 1)
        package = result["packages"][0]
        self.assertTrue(Path(package["zip_path"]).is_file())
        self.assertTrue(package["task_id"].startswith("task-"))

    def test_manifest_and_slides_json_preserve_ids_and_numbers(self):
        deck_id, slide_ids = self._seed_deck()

        result = task_service.create_task_packages(
            self.user_id,
            deck_id,
            range_mode="custom",
            slide_numbers=[2, 4],
        )

        package = result["packages"][0]
        with zipfile.ZipFile(package["zip_path"]) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            slides_payload = json.loads(archive.read("slides.json").decode("utf-8"))
            instructions = archive.read("instructions.md").decode("utf-8")
        self.assertEqual(manifest["package_type"], "intp_chatgpt_explanation_task")
        self.assertEqual(manifest["version"], "1.0")
        self.assertEqual(manifest["deck_id"], deck_id)
        self.assertEqual(manifest["privacy_mode"], "ppt_explanation_task_only")
        self.assertEqual(
            manifest["requested_slides"],
            [
                {"slide_id": slide_ids[1], "slide_number": 2},
                {"slide_id": slide_ids[3], "slide_number": 4},
            ],
        )
        self.assertEqual(slides_payload["task_id"], manifest["task_id"])
        self.assertEqual(
            [(item["slide_id"], item["slide_number"]) for item in slides_payload["slides"]],
            [(slide_ids[1], 2), (slide_ids[3], 4)],
        )
        self.assertIn(manifest["task_id"], instructions)
        self.assertIn("explanation_result.json", instructions)
        self.assertIn("不要只把最终结果打印在聊天正文中", instructions)
        example_text = instructions.split("```json", 1)[1].split("```", 1)[0]
        result_example = json.loads(example_text)
        self.assertRegex(result_example["result_id"], r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
        datetime.fromisoformat(result_example["generated_at"])

    def test_fingerprint_is_stable_for_same_content_and_order_independent(self):
        deck_id, _ = self._seed_deck()
        deck = db.fetch_one("SELECT * FROM ppt_decks WHERE id = ?", (deck_id,))
        slides = db.fetch_all("SELECT * FROM ppt_slides WHERE deck_id = ? ORDER BY slide_number", (deck_id,))

        first = task_service.compute_deck_fingerprint(deck, slides)
        second = task_service.compute_deck_fingerprint(dict(deck), list(reversed(slides)))

        self.assertEqual(first, second)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")

    def test_fingerprint_changes_when_slide_text_changes(self):
        deck_id, slide_ids = self._seed_deck()
        before = task_service.deck_fingerprint(self.user_id, deck_id)

        db.execute("UPDATE ppt_slides SET slide_text = '正文已改变' WHERE id = ?", (slide_ids[1],))
        after = task_service.deck_fingerprint(self.user_id, deck_id)

        self.assertNotEqual(before, after)

    def test_images_are_optional_and_only_included_when_requested(self):
        deck_id, _ = self._seed_deck()
        without_images = task_service.create_task_packages(
            self.user_id, deck_id, range_mode="custom", slide_numbers=[1], include_images=False
        )
        with_images = task_service.create_task_packages(
            self.user_id, deck_id, range_mode="custom", slide_numbers=[1], include_images=True
        )

        with zipfile.ZipFile(without_images["packages"][0]["zip_path"]) as archive:
            names_without = set(archive.namelist())
        with zipfile.ZipFile(with_images["packages"][0]["zip_path"]) as archive:
            names_with = set(archive.namelist())
            slides_payload = json.loads(archive.read("slides.json").decode("utf-8"))
        self.assertFalse(any(name.startswith("images/") for name in names_without))
        self.assertIn("images/slide-001.png", names_with)
        self.assertEqual(slides_payload["slides"][0]["image_path"], "images/slide-001.png")

    def test_default_package_excludes_private_learning_data_and_old_explanation(self):
        deck_id, _ = self._seed_deck()

        result = task_service.create_task_packages(
            self.user_id, deck_id, range_mode="custom", slide_numbers=[1]
        )

        with zipfile.ZipFile(result["packages"][0]["zip_path"]) as archive:
            combined = b"\n".join(archive.read(name) for name in archive.namelist()).decode("utf-8")
        for forbidden in ["私有插问", "私有回答", "私有知识卡", "私有复盘", "旧版私有讲解"]:
            self.assertNotIn(forbidden, combined)

    def test_existing_explanation_is_included_only_after_explicit_opt_in(self):
        deck_id, _ = self._seed_deck()

        result = task_service.create_task_packages(
            self.user_id,
            deck_id,
            range_mode="custom",
            slide_numbers=[1],
            include_existing_explanations=True,
        )

        with zipfile.ZipFile(result["packages"][0]["zip_path"]) as archive:
            slides_payload = json.loads(archive.read("slides.json").decode("utf-8"))
        self.assertEqual(slides_payload["slides"][0]["existing_explanation"], "旧版私有讲解")

    def test_task_record_is_persisted_with_waiting_status(self):
        deck_id, _ = self._seed_deck()

        result = task_service.create_task_packages(
            self.user_id, deck_id, range_mode="custom", slide_numbers=[1, 2]
        )

        task = db.fetch_one(
            "SELECT * FROM chatgpt_explanation_tasks WHERE user_id = ? AND task_id = ?",
            (self.user_id, result["packages"][0]["task_id"]),
        )
        self.assertIsNotNone(task)
        self.assertEqual(task["deck_id"], deck_id)
        self.assertEqual(task["status"], "waiting_result")
        self.assertTrue(Path(task["package_path"]).is_file())
        self.assertEqual(len(json.loads(task["requested_slides_json"])), 2)

    def test_existing_database_without_bridge_tables_migrates_without_data_loss(self):
        deck_id, _ = self._seed_deck()
        db.execute("DROP TABLE chatgpt_explanation_results")
        db.execute("DROP TABLE chatgpt_explanation_tasks")
        db._INITIALIZED_DATABASE_PATH = None

        db.init_db()

        deck = db.fetch_one("SELECT title FROM ppt_decks WHERE id = ?", (deck_id,))
        tables = {
            row["name"]
            for row in db.fetch_all(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'chatgpt_explanation_%'"
            )
        }
        self.assertEqual(deck["title"], "FIR 数字滤波器")
        self.assertEqual(
            tables,
            {"chatgpt_explanation_tasks", "chatgpt_explanation_results"},
        )

    def test_whole_deck_prefers_sections_and_splits_large_sections(self):
        deck_id, _ = self._seed_deck(
            slide_count=9,
            sections=[(1, 1, 6, "第一块"), (2, 7, 9, "第二块")],
        )

        plan = task_service.plan_task_packages(
            self.user_id,
            deck_id,
            range_mode="all",
            max_slides_per_task=4,
        )

        self.assertEqual(plan["package_count"], 3)
        self.assertEqual(
            [[slide["slide_number"] for slide in chunk["slides"]] for chunk in plan["chunks"]],
            [[1, 2, 3, 4], [5, 6], [7, 8, 9]],
        )

    def test_whole_deck_without_sections_uses_fixed_chunks(self):
        deck_id, _ = self._seed_deck(slide_count=45)

        plan = task_service.plan_task_packages(
            self.user_id,
            deck_id,
            range_mode="all",
            max_slides_per_task=20,
        )

        self.assertEqual(plan["package_count"], 3)
        self.assertEqual([len(chunk["slides"]) for chunk in plan["chunks"]], [20, 20, 5])
        self.assertEqual(
            [slide["slide_number"] for chunk in plan["chunks"] for slide in chunk["slides"]],
            list(range(1, 46)),
        )

    def test_whole_deck_keeps_unassigned_pages_in_global_slide_order(self):
        deck_id, _ = self._seed_deck(
            slide_count=9,
            sections=[(1, 2, 4, "第一块"), (2, 6, 8, "第二块")],
        )

        plan = task_service.plan_task_packages(
            self.user_id,
            deck_id,
            range_mode="all",
            max_slides_per_task=4,
        )

        self.assertEqual(
            [[slide["slide_number"] for slide in chunk["slides"]] for chunk in plan["chunks"]],
            [[1], [2, 3, 4], [5], [6, 7, 8], [9]],
        )

    def test_range_parser_and_user_scope_validation(self):
        self.assertEqual(task_service.parse_slide_number_spec("1-3, 5, 3"), [1, 2, 3, 5])
        with self.assertRaisesRegex(ValueError, "页码"):
            task_service.parse_slide_number_spec("3-1")
        other_deck_id, _ = self._seed_deck(user_id=99)
        with self.assertRaisesRegex(ValueError, "PPT"):
            task_service.plan_task_packages(self.user_id, other_deck_id, range_mode="all")


if __name__ == "__main__":
    unittest.main()
