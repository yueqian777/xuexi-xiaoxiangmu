from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import db
from pages import ppt_management
from repositories import ppt_repository
from services import (
    course_service,
    ppt_explanation_import_service,
    ppt_service,
    question_to_knowledge_service,
    study_asset_service,
)


class CourseWriteIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "study_manager.db"
        self.patchers = [
            patch.object(db, "DATA_DIR", self.data_dir),
            patch.object(db, "DATABASE_PATH", self.db_path),
            patch.object(ppt_explanation_import_service, "DATA_DIR", self.data_dir),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, db, "_INITIALIZED_DATABASE_PATH", None)
        db._INITIALIZED_DATABASE_PATH = None
        db.init_db()
        self.user_id = 41

    def test_regular_deck_import_links_an_owner_specific_course(self):
        other_course_id = course_service.ensure_course_for_subject(99, "信号与系统")
        source = self.data_dir / "signals.pdf"
        source.write_bytes(b"pdf")

        with patch.object(ppt_service, "require_login", return_value=SimpleNamespace(id=self.user_id)):
            deck_id = ppt_service._save_deck_records(
                source,
                [],
                {},
                subject=" 信号与系统 ",
                title="系统函数",
            )

        deck = db.fetch_one(
            "SELECT user_id, subject, course_id FROM ppt_decks WHERE id = ?",
            (deck_id,),
        )
        course = db.fetch_one("SELECT user_id, name FROM courses WHERE id = ?", (deck["course_id"],))
        self.assertEqual(deck["user_id"], self.user_id)
        self.assertEqual(deck["subject"], "信号与系统")
        self.assertEqual(course, {"user_id": self.user_id, "name": "信号与系统"})
        self.assertNotEqual(deck["course_id"], other_course_id)

    def test_deck_management_subject_edit_relinks_the_owned_course_atomically(self):
        original_course_id = course_service.ensure_course_for_subject(
            self.user_id,
            "信号与系统",
        )
        foreign_course_id = course_service.ensure_course_for_subject(99, "自动控制")
        deck_id, slide_id = self._create_deck_and_slide(
            subject="信号与系统",
            course_id=original_course_id,
        )
        question_id = db.insert_and_get_id(
            """
            INSERT INTO slide_questions (user_id, slide_id, question, answer, model)
            VALUES (?, ?, '为什么闭环稳定？', '取决于极点。', 'test')
            """,
            (self.user_id, slide_id),
        )
        slide_card_id = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, one_sentence, source_slide_id, course_id
            ) VALUES (?, '信号与系统', '闭环稳定', '检查闭环极点', ?, ?)
            """,
            (self.user_id, slide_id, original_course_id),
        )
        question_card_id = db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, subject, topic, one_sentence, source_question_id, course_id
            ) VALUES (?, '信号与系统', '稳定判据', '极点位于稳定域', ?, ?)
            """,
            (self.user_id, question_id, original_course_id),
        )

        updated = ppt_management._save_deck_management_rows(
            self.user_id,
            [
                {
                    "id": deck_id,
                    "sort_order": 3,
                    "status": "使用中",
                    "category": "专业课",
                    "subject": " 自动控制 ",
                    "title": "闭环系统",
                }
            ],
        )

        deck = db.fetch_one(
            "SELECT subject, course_id, sort_order, title FROM ppt_decks WHERE id = ?",
            (deck_id,),
        )
        course = db.fetch_one(
            "SELECT user_id, name FROM courses WHERE id = ?",
            (deck["course_id"],),
        )
        self.assertEqual(updated, 1)
        self.assertEqual(deck["subject"], "自动控制")
        self.assertEqual(deck["sort_order"], 3)
        self.assertEqual(deck["title"], "闭环系统")
        self.assertEqual(course, {"user_id": self.user_id, "name": "自动控制"})
        self.assertNotEqual(deck["course_id"], original_course_id)
        self.assertNotEqual(deck["course_id"], foreign_course_id)
        linked_cards = db.fetch_all(
            """
            SELECT id, course_id
            FROM knowledge_cards
            WHERE id IN (?, ?)
            ORDER BY id
            """,
            (slide_card_id, question_card_id),
        )
        self.assertEqual(
            [int(card["course_id"]) for card in linked_cards],
            [int(deck["course_id"]), int(deck["course_id"])],
        )

    def test_deck_management_metadata_edit_preserves_historical_canonical_course(self):
        historical = course_service.create_course(self.user_id, "数字信号处理")
        deck_id, _ = self._create_deck_and_slide(
            subject="旧科目标签",
            course_id=historical["id"],
        )
        course_service.complete_course(self.user_id, historical["id"])

        updated = ppt_management._save_deck_management_rows(
            self.user_id,
            [
                {
                    "id": deck_id,
                    "sort_order": 4,
                    "status": "使用中",
                    "category": "历史资料",
                    "subject": "旧科目标签",
                    "title": "只修改标题",
                }
            ],
        )

        deck = db.fetch_one(
            "SELECT subject, course_id, sort_order, title FROM ppt_decks WHERE id = ?",
            (deck_id,),
        )
        self.assertEqual(updated, 1)
        self.assertEqual(deck["course_id"], historical["id"])
        self.assertEqual(deck["title"], "只修改标题")
        self.assertEqual(
            course_service.get_course(self.user_id, historical["id"])["status"],
            "completed",
        )
        self.assertIsNone(
            db.fetch_one(
                "SELECT id FROM courses WHERE user_id = ? AND name = '旧科目标签'",
                (self.user_id,),
            )
        )

    def test_deck_management_rejects_blank_subject_without_partial_updates(self):
        course_id = course_service.ensure_course_for_subject(self.user_id, "信号与系统")
        deck_id, _ = self._create_deck_and_slide(
            subject="信号与系统",
            course_id=course_id,
        )

        with self.assertRaisesRegex(ValueError, "科目不能为空"):
            ppt_management._save_deck_management_rows(
                self.user_id,
                [
                    {
                        "id": deck_id,
                        "sort_order": 9,
                        "status": "使用中",
                        "category": "",
                        "subject": "   ",
                        "title": "不应保存",
                    }
                ],
            )

        deck = db.fetch_one(
            "SELECT subject, course_id, sort_order, title FROM ppt_decks WHERE id = ?",
            (deck_id,),
        )
        self.assertEqual(deck["subject"], "信号与系统")
        self.assertEqual(deck["course_id"], course_id)
        self.assertEqual(deck["sort_order"], 0)
        self.assertEqual(deck["title"], "来源资料")

    def test_shared_deck_import_links_each_subject_to_its_course(self):
        zip_path = self._build_two_deck_share()

        result = ppt_explanation_import_service.import_share_package(self.user_id, zip_path)

        decks = db.fetch_all(
            """
            SELECT d.subject, d.course_id, c.user_id AS course_user_id, c.name AS course_name
            FROM ppt_decks d
            JOIN courses c ON c.id = d.course_id AND c.user_id = d.user_id
            WHERE d.user_id = ?
            ORDER BY d.id ASC
            """,
            (self.user_id,),
        )
        self.assertEqual(len(result["deck_ids"]), 2)
        self.assertEqual(
            [(row["subject"], row["course_name"]) for row in decks],
            [("信号与系统", "信号与系统"), ("自动控制", "自动控制")],
        )
        self.assertTrue(all(row["course_user_id"] == self.user_id for row in decks))

    def test_subjectless_shared_deck_uses_owned_active_uncategorized_course(self):
        zip_path = self._build_subjectless_share()

        result = ppt_explanation_import_service.import_share_package(self.user_id, zip_path)

        deck = db.fetch_one(
            """
            SELECT d.subject, d.course_id, c.user_id AS course_user_id,
                   c.name AS course_name, c.status AS course_status
            FROM ppt_decks d
            JOIN courses c ON c.id = d.course_id AND c.user_id = d.user_id
            WHERE d.user_id = ? AND d.id = ?
            """,
            (self.user_id, result["deck_id"]),
        )
        self.assertIsNotNone(deck)
        self.assertIsInstance(deck["course_id"], int)
        self.assertEqual(deck["subject"], "未分类")
        self.assertEqual(deck["course_user_id"], self.user_id)
        self.assertEqual(deck["course_name"], "未分类")
        self.assertEqual(deck["course_status"], "active")

    def test_question_card_prefers_the_source_deck_course(self):
        canonical_course_id = course_service.create_course(self.user_id, "数字信号处理")["id"]
        deck_id, slide_id = self._create_deck_and_slide(
            subject="旧科目标签",
            course_id=canonical_course_id,
        )
        question_id = ppt_repository.create_slide_question_tree_node(
            self.user_id,
            slide_id,
            "为什么单位圆决定频响？",
            "因为在单位圆上取样系统函数。",
            "model",
        )

        result = question_to_knowledge_service.convert_question_to_knowledge(self.user_id, question_id)

        card = db.fetch_one(
            "SELECT subject, course_id, source_deck_id FROM knowledge_cards WHERE id = ?",
            (result["knowledge_id"],),
        )
        self.assertEqual(card["source_deck_id"], deck_id)
        self.assertEqual(card["subject"], "旧科目标签")
        self.assertEqual(card["course_id"], canonical_course_id)
        self.assertIsNone(
            db.fetch_one(
                "SELECT id FROM courses WHERE user_id = ? AND name = '旧科目标签'",
                (self.user_id,),
            )
        )

    def test_question_card_uses_subject_course_when_source_deck_is_unlinked(self):
        _, slide_id = self._create_deck_and_slide(subject="概率论", course_id=None)
        question_id = ppt_repository.create_slide_question_tree_node(
            self.user_id,
            slide_id,
            "条件概率如何解释？",
            "缩小样本空间。",
            "model",
        )

        result = question_to_knowledge_service.convert_question_to_knowledge(self.user_id, question_id)

        card = db.fetch_one(
            """
            SELECT kc.course_id, c.user_id AS course_user_id, c.name AS course_name
            FROM knowledge_cards kc
            JOIN courses c ON c.id = kc.course_id
            WHERE kc.id = ?
            """,
            (result["knowledge_id"],),
        )
        self.assertEqual(card["course_user_id"], self.user_id)
        self.assertEqual(card["course_name"], "概率论")

    def test_study_assets_link_session_and_derived_cards_to_one_course(self):
        course = course_service.create_course(self.user_id, "通信原理")
        canonical_course_id = int(course["id"])
        deck_id, _ = self._create_deck_and_slide(
            subject="通信原理",
            course_id=canonical_course_id,
        )
        assets = {
            "study_session": {
                "date": "2026-08-23",
                "subject": "AI 生成的展示标签",
                "chapter": "调制",
                "title": "AM 阅读复盘",
                "main_question": "为什么需要调制？",
            },
            "knowledge_cards": [
                {
                    "subject": "不同的生成标签",
                    "topic": "调制目的",
                    "one_sentence": "把基带搬移到适合信道的频段。",
                    "need_review": False,
                }
            ],
        }

        with patch.object(
            study_asset_service,
            "require_login",
            return_value=SimpleNamespace(id=self.user_id),
        ):
            session_id, knowledge_ids = study_asset_service.save_study_assets(
                assets,
                source_deck_id=deck_id,
                fallback_subject="",
                fallback_chapter="",
            )

        session = db.fetch_one(
            "SELECT subject, course_id FROM study_sessions WHERE id = ?",
            (session_id,),
        )
        card = db.fetch_one(
            "SELECT subject, course_id, source_session_id FROM knowledge_cards WHERE id = ?",
            (knowledge_ids[0],),
        )
        stored_course = db.fetch_one("SELECT user_id, name FROM courses WHERE id = ?", (session["course_id"],))
        self.assertEqual(stored_course, {"user_id": self.user_id, "name": "通信原理"})
        self.assertEqual(session["course_id"], canonical_course_id)
        self.assertEqual(
            db.fetch_one("SELECT COUNT(*) AS count FROM courses WHERE user_id = ?", (self.user_id,))["count"],
            1,
        )
        self.assertEqual(card["source_session_id"], session_id)
        self.assertEqual(card["subject"], "不同的生成标签")
        self.assertEqual(card["course_id"], session["course_id"])

    def test_study_assets_require_reactivation_of_the_source_deck_course(self):
        transitions = (
            ("completed", course_service.complete_course),
            ("archived", course_service.archive_course),
        )
        for status, transition in transitions:
            with self.subTest(status=status):
                course_name = f"历史沉淀-{status}"
                draft_subject = f"不应新建-{status}"
                course = course_service.create_course(self.user_id, course_name)
                deck_id, _ = self._create_deck_and_slide(
                    subject=course_name,
                    course_id=course["id"],
                )
                transition(self.user_id, course["id"])
                assets = {
                    "study_session": {
                        "date": "2026-08-23",
                        "subject": draft_subject,
                        "chapter": "历史资料",
                    },
                    "knowledge_cards": [
                        {
                            "subject": draft_subject,
                            "topic": "历史知识点",
                            "one_sentence": "只有重新激活后才能写入。",
                            "need_review": True,
                        }
                    ],
                }

                with patch.object(
                    study_asset_service,
                    "require_login",
                    return_value=SimpleNamespace(id=self.user_id),
                ):
                    with self.assertRaisesRegex(ValueError, "重新激活"):
                        study_asset_service.save_study_assets(
                            assets,
                            source_deck_id=deck_id,
                            fallback_subject=course_name,
                            fallback_chapter="",
                        )

                self.assertEqual(
                    db.fetch_one(
                        "SELECT COUNT(*) AS count FROM study_sessions WHERE user_id = ? AND subject = ?",
                        (self.user_id, draft_subject),
                    )["count"],
                    0,
                )
                self.assertEqual(
                    db.fetch_one(
                        "SELECT COUNT(*) AS count FROM courses WHERE user_id = ? AND name = ?",
                        (self.user_id, draft_subject),
                    )["count"],
                    0,
                )

                course_service.reactivate_course(self.user_id, course["id"])
                with patch.object(
                    study_asset_service,
                    "require_login",
                    return_value=SimpleNamespace(id=self.user_id),
                ):
                    session_id, knowledge_ids = study_asset_service.save_study_assets(
                        assets,
                        source_deck_id=deck_id,
                        fallback_subject=course_name,
                        fallback_chapter="",
                    )
                self.assertEqual(
                    db.fetch_one("SELECT course_id FROM study_sessions WHERE id = ?", (session_id,))["course_id"],
                    course["id"],
                )
                self.assertEqual(
                    db.fetch_one("SELECT course_id FROM knowledge_cards WHERE id = ?", (knowledge_ids[0],))["course_id"],
                    course["id"],
                )
                self.assertEqual(
                    db.fetch_one(
                        "SELECT COUNT(*) AS count FROM course_learning_phases WHERE user_id = ? AND course_id = ?",
                        (self.user_id, course["id"]),
                    )["count"],
                    2,
                )

    def test_study_assets_reject_unbound_or_foreign_source_decks(self):
        assets = {
            "study_session": {"subject": "不应落库", "chapter": "边界"},
            "knowledge_cards": [{"topic": "边界", "one_sentence": "不应落库"}],
        }
        unbound_deck_id, _ = self._create_deck_and_slide(subject="无课程", course_id=None)
        foreign_course = course_service.create_course(99, "外部课程")
        foreign_deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, filename, title, subject, file_path, slide_count, course_id
            ) VALUES (99, 'foreign.pdf', '外部资料', '外部课程', 'foreign.pdf', 1, ?)
            """,
            (foreign_course["id"],),
        )

        with patch.object(
            study_asset_service,
            "require_login",
            return_value=SimpleNamespace(id=self.user_id),
        ):
            for deck_id in (unbound_deck_id, foreign_deck_id):
                with self.subTest(deck_id=deck_id):
                    with self.assertRaisesRegex(ValueError, "重新激活"):
                        study_asset_service.save_study_assets(
                            assets,
                            source_deck_id=deck_id,
                            fallback_subject="不应落库",
                            fallback_chapter="",
                        )

        self.assertEqual(
            db.fetch_one(
                "SELECT COUNT(*) AS count FROM study_sessions WHERE user_id = ? AND subject = '不应落库'",
                (self.user_id,),
            )["count"],
            0,
        )

    def _create_deck_and_slide(self, *, subject: str, course_id: int | None) -> tuple[int, int]:
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, filename, title, subject, file_path, slide_count, course_id
            )
            VALUES (?, 'source.pdf', '来源资料', ?, 'source.pdf', 1, ?)
            """,
            (self.user_id, subject, course_id),
        )
        slide_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_slides (user_id, deck_id, slide_number, title, slide_text)
            VALUES (?, ?, 1, '来源页', '来源页正文')
            """,
            (self.user_id, deck_id),
        )
        return deck_id, slide_id

    def _build_two_deck_share(self) -> Path:
        zip_path = self.data_dir / "share.zip"
        manifest = {
            "package_type": "ppt_explanation_share",
            "version": "1.0",
            "package_id": "course-write-share",
            "subject": "综合课程",
            "deck_title": "两份资料",
            "exported_at": "2026-08-23T10:00:00",
            "privacy_mode": "public_ppt_explanation_only",
            "decks": [
                {
                    "subject": "信号与系统",
                    "deck_title": "系统函数",
                    "filename": "signals.pdf",
                    "slide_count": 1,
                    "slides": [
                        {
                            "slide_number": 1,
                            "title": "系统函数",
                            "markdown_path": "signals/slide-001.md",
                            "image_path": "signals/slide-001.png",
                        }
                    ],
                },
                {
                    "subject": "自动控制",
                    "deck_title": "PID",
                    "filename": "control.pdf",
                    "slide_count": 1,
                    "slides": [
                        {
                            "slide_number": 1,
                            "title": "PID",
                            "markdown_path": "control/slide-001.md",
                            "image_path": "control/slide-001.png",
                        }
                    ],
                },
            ],
        }
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            for folder in ("signals", "control"):
                archive.writestr(
                    f"{folder}/slide-001.md",
                    "# Slide 001\n\n## PPT/PDF 页面文字\n\n正文\n\n## AI 逐页讲解\n\n讲解",
                )
                archive.writestr(f"{folder}/slide-001.png", b"image")
        return zip_path

    def _build_subjectless_share(self) -> Path:
        zip_path = self.data_dir / "subjectless-share.zip"
        manifest = {
            "package_type": "ppt_explanation_share",
            "version": "1.0",
            "package_id": "subjectless-course-write-share",
            "subject": "   ",
            "deck_title": "未分类资料",
            "exported_at": "2026-08-23T10:00:00",
            "privacy_mode": "public_ppt_explanation_only",
            "slides": [
                {
                    "slide_number": 1,
                    "title": "未分类页",
                    "markdown_path": "slides/slide-001.md",
                    "image_path": "slides/slide-001.png",
                }
            ],
        }
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            archive.writestr(
                "slides/slide-001.md",
                "# Slide 001\n\n## PPT/PDF 页面文字\n\n正文\n\n## AI 逐页讲解\n\n讲解",
            )
            archive.writestr("slides/slide-001.png", b"image")
        return zip_path


if __name__ == "__main__":
    unittest.main()
