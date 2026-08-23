from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch

import db
from repositories import ppt_repository
from services.active_learning_context_service import set_active_deck
from services import course_service, review_service, stats_service
from services import daily_ai_review_service
from services.daily_ai_review_service import collect_review_candidates
from services.question_to_knowledge_service import convert_question_to_knowledge


class CourseLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
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

        self.user_id = 41
        self.other_user_id = 42

    def _create_course(self, name: str, *, user_id: int | None = None) -> dict:
        return course_service.create_course(
            self.user_id if user_id is None else user_id,
            name,
        )

    def _seed_deck(
        self,
        course_id: int,
        title: str,
        *,
        slide_count: int = 1,
        user_id: int | None = None,
    ) -> tuple[int, list[int]]:
        owner_id = self.user_id if user_id is None else user_id
        deck_id = db.insert_and_get_id(
            """
            INSERT INTO ppt_decks (
                user_id, course_id, filename, title, subject, file_path, slide_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id,
                course_id,
                f"{title}.pdf",
                title,
                "信号与系统",
                f"{title}.pdf",
                slide_count,
            ),
        )
        slide_ids = [
            db.insert_and_get_id(
                """
                INSERT INTO ppt_slides (
                    user_id, deck_id, slide_number, title, slide_text
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (owner_id, deck_id, number, f"第 {number} 页", f"正文 {number}"),
            )
            for number in range(1, slide_count + 1)
        ]
        return deck_id, slide_ids

    def _seed_question(
        self,
        slide_id: int,
        question: str,
        *,
        user_id: int | None = None,
    ) -> int:
        return db.insert_and_get_id(
            """
            INSERT INTO slide_questions (
                user_id, slide_id, question, answer, model
            )
            VALUES (?, ?, ?, '测试回答', 'test-model')
            """,
            (self.user_id if user_id is None else user_id, slide_id, question),
        )

    def _seed_knowledge(
        self,
        course_id: int,
        topic: str,
        *,
        mastery: int,
        user_id: int | None = None,
    ) -> int:
        return db.insert_and_get_id(
            """
            INSERT INTO knowledge_cards (
                user_id, course_id, subject, topic, one_sentence, mastery, need_review
            )
            VALUES (?, ?, '信号与系统', ?, ?, ?, ?)
            """,
            (
                self.user_id if user_id is None else user_id,
                course_id,
                topic,
                f"{topic} 核心结论",
                mastery,
                int(mastery < 70),
            ),
        )

    def _seed_review(
        self,
        knowledge_id: int,
        *,
        status: str = "待复习",
        user_id: int | None = None,
    ) -> int:
        return db.insert_and_get_id(
            """
            INSERT INTO review_tasks (
                user_id, knowledge_id, review_date, review_stage, status
            )
            VALUES (?, ?, '2026-08-23', '第 1 天复习', ?)
            """,
            (
                self.user_id if user_id is None else user_id,
                knowledge_id,
                status,
            ),
        )

    @staticmethod
    def _weak_point_topics(summary: dict) -> set[str]:
        topics: set[str] = set()
        for item in summary["weak_points"]:
            if isinstance(item, str):
                topics.add(item)
            else:
                topics.add(str(item["topic"]))
        return topics

    def test_new_course_defaults_to_active(self):
        created = self._create_course("信号与系统")

        self.assertGreater(created["id"], 0)
        self.assertEqual(created["user_id"], self.user_id)
        self.assertEqual(created["name"], "信号与系统")
        self.assertEqual(created["status"], "active")
        self.assertEqual(course_service.get_course(self.user_id, created["id"]), created)

    def test_same_user_cannot_create_two_active_courses_with_the_same_name(self):
        first = self._create_course(" 信号与系统 ")

        with self.assertRaisesRegex(ValueError, "正在学习"):
            self._create_course("信号与系统")

        active = course_service.list_courses(self.user_id, statuses=["active"])
        self.assertEqual([row["id"] for row in active], [first["id"]])

    def test_concurrent_subject_writes_converge_on_one_active_course_and_phase(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            course_ids = list(
                pool.map(
                    lambda _: course_service.ensure_course_for_subject(
                        self.user_id,
                        "通信原理",
                    ),
                    range(8),
                )
            )

        self.assertEqual(len(set(course_ids)), 1)
        course_id = course_ids[0]
        self.assertEqual(
            db.fetch_one(
                """
                SELECT COUNT(*) AS count
                FROM courses
                WHERE user_id = ? AND name = '通信原理' AND status = 'active'
                """,
                (self.user_id,),
            )["count"],
            1,
        )
        self.assertEqual(
            db.fetch_one(
                """
                SELECT COUNT(*) AS count
                FROM course_learning_phases
                WHERE user_id = ? AND course_id = ?
                """,
                (self.user_id, course_id),
            )["count"],
            1,
        )

    def test_course_can_be_completed_or_archived(self):
        completed_course = self._create_course("数字信号处理")
        archived_course = self._create_course("工程伦理")

        completed = course_service.complete_course(self.user_id, completed_course["id"])
        archived = course_service.archive_course(self.user_id, archived_course["id"])

        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["completed_at"])
        self.assertEqual(archived["status"], "archived")
        self.assertTrue(archived["archived_at"])
        self.assertEqual(
            course_service.get_course(self.user_id, completed_course["id"])["status"],
            "completed",
        )
        self.assertEqual(
            course_service.get_course(self.user_id, archived_course["id"])["status"],
            "archived",
        )

    def test_archived_course_must_be_reactivated_before_completion(self):
        course = self._create_course("归档课程")
        course_service.archive_course(self.user_id, course["id"])

        with self.assertRaisesRegex(ValueError, "重新激活"):
            course_service.complete_course(self.user_id, course["id"])

        detail = course_service.get_course_detail(self.user_id, course["id"])
        self.assertEqual(detail["course"]["status"], "archived")
        self.assertEqual(detail["learning_phases"][0]["outcome"], "archived")

    def test_new_subject_write_does_not_disappear_into_same_named_archived_course(self):
        historical = self._create_course("信号与系统")
        course_service.archive_course(self.user_id, historical["id"])

        new_course_id = course_service.ensure_course_for_subject(
            self.user_id,
            "信号与系统",
        )

        self.assertNotEqual(new_course_id, historical["id"])
        self.assertEqual(
            course_service.get_course(self.user_id, new_course_id)["status"],
            "active",
        )
        self.assertEqual(
            course_service.get_course(self.user_id, historical["id"])["status"],
            "archived",
        )

    def test_completing_course_keeps_decks_questions_and_knowledge_cards(self):
        course = self._create_course("FIR 滤波器")
        deck_id, slide_ids = self._seed_deck(course["id"], "FIR 窗函数", slide_count=2)
        question_id = self._seed_question(slide_ids[0], "为什么需要窗函数？")
        knowledge_id = self._seed_knowledge(
            course["id"],
            "线性相位条件",
            mastery=65,
        )

        course_service.complete_course(self.user_id, course["id"])

        self.assertIsNotNone(
            db.fetch_one(
                "SELECT id FROM ppt_decks WHERE id = ? AND user_id = ? AND course_id = ?",
                (deck_id, self.user_id, course["id"]),
            )
        )
        self.assertEqual(
            db.fetch_one(
                "SELECT COUNT(*) AS count FROM ppt_slides WHERE deck_id = ? AND user_id = ?",
                (deck_id, self.user_id),
            )["count"],
            2,
        )
        self.assertIsNotNone(
            db.fetch_one(
                "SELECT id FROM slide_questions WHERE id = ? AND user_id = ?",
                (question_id, self.user_id),
            )
        )
        self.assertIsNotNone(
            db.fetch_one(
                "SELECT id FROM knowledge_cards WHERE id = ? AND user_id = ? AND course_id = ?",
                (knowledge_id, self.user_id, course["id"]),
            )
        )

    def test_reactivate_starts_a_new_learning_phase_without_overwriting_history(self):
        course = self._create_course("数字电子技术")
        course_service.complete_course(self.user_id, course["id"])
        completed_detail = course_service.get_course_detail(self.user_id, course["id"])
        old_phases = completed_detail["learning_phases"]

        reactivated = course_service.reactivate_course(self.user_id, course["id"])
        active_detail = course_service.get_course_detail(self.user_id, course["id"])
        phases = active_detail["learning_phases"]

        self.assertEqual(reactivated["status"], "active")
        self.assertEqual(active_detail["course"]["status"], "active")
        self.assertEqual(len(old_phases), 1)
        self.assertEqual(len(phases), 2)
        self.assertEqual(phases[0], old_phases[0])
        self.assertNotEqual(phases[1]["id"], phases[0]["id"])
        self.assertTrue(phases[1]["started_at"])
        self.assertIn(phases[1].get("ended_at"), (None, ""))

    def test_historical_course_learning_writes_require_reactivation(self):
        course = self._create_course("历史课程写保护")
        _, slide_ids = self._seed_deck(course["id"], "历史课程课件")
        existing_question_id = self._seed_question(slide_ids[0], "原有问题")
        course_service.complete_course(self.user_id, course["id"])

        with self.assertRaisesRegex(ValueError, "重新激活"):
            ppt_repository.add_slide_question(
                self.user_id,
                slide_ids[0],
                "结束后新增的问题",
                "不应写入",
                "test-model",
            )
        with self.assertRaisesRegex(ValueError, "重新激活"):
            convert_question_to_knowledge(
                self.user_id,
                existing_question_id,
            )
        self.assertEqual(
            db.fetch_one(
                "SELECT COUNT(*) AS count FROM slide_questions WHERE slide_id = ?",
                (slide_ids[0],),
            )["count"],
            1,
        )
        self.assertEqual(
            db.fetch_one(
                "SELECT COUNT(*) AS count FROM knowledge_cards WHERE user_id = ?",
                (self.user_id,),
            )["count"],
            0,
        )

        course_service.reactivate_course(self.user_id, course["id"])
        new_question_id = ppt_repository.add_slide_question(
            self.user_id,
            slide_ids[0],
            "重新激活后的问题",
            "允许写入",
            "test-model",
        )
        converted = convert_question_to_knowledge(
            self.user_id,
            existing_question_id,
        )

        self.assertGreater(new_question_id, existing_question_id)
        self.assertGreater(int(converted["knowledge_id"]), 0)
        phases = course_service.get_course_detail(
            self.user_id,
            course["id"],
        )["learning_phases"]
        self.assertEqual(len(phases), 2)
        self.assertIsNone(phases[-1]["ended_at"])

    def test_reactivate_rejects_same_named_active_course_without_changing_history(self):
        historical = self._create_course("信号与系统")
        course_service.complete_course(self.user_id, historical["id"])
        current = self._create_course("信号与系统")
        phase_count_before = len(
            course_service.get_course_detail(self.user_id, historical["id"])["learning_phases"]
        )

        with self.assertRaisesRegex(ValueError, "同名课程"):
            course_service.reactivate_course(self.user_id, historical["id"])

        self.assertEqual(
            course_service.get_course(self.user_id, historical["id"])["status"],
            "completed",
        )
        self.assertEqual(
            course_service.get_course(self.user_id, current["id"])["status"],
            "active",
        )
        self.assertEqual(
            len(
                course_service.get_course_detail(
                    self.user_id,
                    historical["id"],
                )["learning_phases"]
            ),
            phase_count_before,
        )

    def test_course_reads_lists_and_mutations_are_isolated_by_user(self):
        own_active = self._create_course("本人的课程")
        own_completed = self._create_course("本人的历史课程")
        foreign = self._create_course("其他用户课程", user_id=self.other_user_id)
        course_service.complete_course(self.user_id, own_completed["id"])

        all_owned = course_service.list_courses(self.user_id)
        active_owned = course_service.list_courses(self.user_id, statuses=["active"])
        completed_owned = course_service.list_courses(
            self.user_id,
            statuses=["completed"],
        )

        self.assertEqual({item["id"] for item in all_owned}, {own_active["id"], own_completed["id"]})
        self.assertEqual([item["id"] for item in active_owned], [own_active["id"]])
        self.assertEqual([item["id"] for item in completed_owned], [own_completed["id"]])
        self.assertIsNone(course_service.get_course(self.user_id, foreign["id"]))
        self.assertIsNone(course_service.get_course_summary(self.user_id, foreign["id"]))
        self.assertIsNone(course_service.get_course_detail(self.user_id, foreign["id"]))
        self.assertIsNone(course_service.complete_course(self.user_id, foreign["id"]))
        self.assertIsNone(course_service.archive_course(self.user_id, foreign["id"]))
        self.assertIsNone(course_service.reactivate_course(self.user_id, foreign["id"]))
        self.assertEqual(
            course_service.get_course(self.other_user_id, foreign["id"])["status"],
            "active",
        )

    def test_course_summary_counts_learning_assets_reviews_and_weak_points(self):
        course = self._create_course("信号与系统")
        db.insert_and_get_id(
            """
            INSERT INTO study_sessions (
                user_id, course_id, date, subject, title, main_question
            )
            VALUES (?, ?, '2026-01-02', '信号与系统', '开课学习', '系统如何响应？')
            """,
            (self.user_id, course["id"]),
        )
        _, first_slides = self._seed_deck(
            course["id"],
            "连续时间系统",
            slide_count=2,
        )
        _, second_slides = self._seed_deck(
            course["id"],
            "Z 变换",
            slide_count=1,
        )
        self._seed_question(first_slides[0], "卷积为什么表示系统响应？")
        self._seed_question(second_slides[0], "ROC 为什么决定稳定性？")
        weak_knowledge_id = self._seed_knowledge(
            course["id"],
            "极零图与频响关系",
            mastery=55,
        )
        strong_knowledge_id = self._seed_knowledge(
            course["id"],
            "线性相位条件",
            mastery=88,
        )
        self._seed_review(weak_knowledge_id, status="待复习")
        self._seed_review(weak_knowledge_id, status="待复习")
        self._seed_review(strong_knowledge_id, status="已完成")

        _, foreign_slides = self._seed_deck(
            course["id"],
            "其他用户课件",
            slide_count=2,
            user_id=self.other_user_id,
        )
        self._seed_question(
            foreign_slides[0],
            "不应计入的问题",
            user_id=self.other_user_id,
        )
        foreign_knowledge_id = self._seed_knowledge(
            course["id"],
            "其他用户薄弱点",
            mastery=10,
            user_id=self.other_user_id,
        )
        self._seed_review(
            foreign_knowledge_id,
            status="待复习",
            user_id=self.other_user_id,
        )

        course_service.complete_course(self.user_id, course["id"])
        summary = course_service.get_course_summary(self.user_id, course["id"])

        self.assertEqual(summary["course_id"], course["id"])
        self.assertEqual(summary["deck_count"], 2)
        self.assertEqual(summary["slide_count"], 3)
        self.assertEqual(summary["question_count"], 2)
        self.assertEqual(summary["knowledge_count"], 2)
        self.assertEqual(summary["review_count"], 3)
        self.assertEqual(summary["completed_review_count"], 1)
        self.assertEqual(summary["pending_review_count"], 2)
        self.assertEqual(summary["study_session_count"], 1)
        self.assertTrue(summary["started_at"].startswith("2026-01-02"))
        self.assertTrue(summary["last_activity_at"])
        self.assertEqual(self._weak_point_topics(summary), {"极零图与频响关系"})
        self.assertTrue(summary["future_review_advice"])
        self.assertIn("复习", summary["future_review_advice"])

    def test_dashboard_snapshot_shows_only_active_courses_and_all_status_counts(self):
        active = self._create_course("当前课程")
        completed = self._create_course("已完成课程")
        archived = self._create_course("已归档课程")
        course_service.complete_course(self.user_id, completed["id"])
        course_service.archive_course(self.user_id, archived["id"])
        self._create_course("其他用户当前课程", user_id=self.other_user_id)

        snapshot = course_service.get_dashboard_snapshot(self.user_id)

        self.assertEqual(
            snapshot["status_counts"],
            {"active": 1, "completed": 1, "archived": 1},
        )
        self.assertEqual([item["id"] for item in snapshot["active_courses"]], [active["id"]])
        self.assertEqual(snapshot["current_course"]["id"], active["id"])
        self.assertEqual(snapshot["current_course"]["status"], "active")
        self.assertNotIn(
            archived["id"],
            {item["id"] for item in snapshot["active_courses"]},
        )

    def test_dashboard_snapshot_uses_none_when_there_is_no_active_course(self):
        completed = self._create_course("只有历史课程")
        course_service.complete_course(self.user_id, completed["id"])

        snapshot = course_service.get_dashboard_snapshot(self.user_id)

        self.assertEqual(snapshot["active_courses"], [])
        self.assertIsNone(snapshot["current_course"])
        self.assertEqual(
            snapshot["status_counts"],
            {"active": 0, "completed": 1, "archived": 0},
        )

    def test_dashboard_task_sources_exclude_archived_courses_by_default_opt_in(self):
        active = self._create_course("当前复习")
        archived = self._create_course("归档复习")
        active_card = self._seed_knowledge(active["id"], "当前薄弱点", mastery=30)
        archived_card = self._seed_knowledge(archived["id"], "归档薄弱点", mastery=10)
        self._seed_review(active_card)
        self._seed_review(archived_card)
        course_service.archive_course(self.user_id, archived["id"])

        visible_reviews = review_service.get_today_review_tasks(
            user_id=self.user_id,
            include_archived=False,
        )
        visible_cards = stats_service.low_mastery_cards(
            user_id=self.user_id,
            include_archived=False,
        )
        ai_candidates = collect_review_candidates(user_id=self.user_id)
        all_ai_candidates = collect_review_candidates(
            user_id=self.user_id,
            include_archived=True,
        )

        self.assertEqual({row["knowledge_id"] for row in visible_reviews}, {active_card})
        self.assertEqual({row["id"] for row in visible_cards}, {active_card})
        self.assertEqual({row["knowledge_id"] for row in ai_candidates}, {active_card})
        self.assertEqual(
            {row["knowledge_id"] for row in all_ai_candidates},
            {active_card, archived_card},
        )

        db.execute(
            """
            INSERT INTO study_sessions (
                user_id, course_id, date, subject, title, main_question, blockers
            ) VALUES (?, ?, '2026-08-22', '当前复习', '当前记录', '为什么？', '当前卡点')
            """,
            (self.user_id, active["id"]),
        )
        db.execute(
            """
            INSERT INTO study_sessions (
                user_id, course_id, date, subject, title, main_question, blockers
            ) VALUES (?, ?, '2026-08-23', '归档复习', '归档记录', '为什么？', '归档卡点')
            """,
            (self.user_id, archived["id"]),
        )
        db.execute(
            """
            INSERT INTO knowledge_links (
                user_id, source_knowledge_id, target_knowledge_id, relation_type
            ) VALUES (?, ?, ?, '对比概念')
            """,
            (self.user_id, active_card, archived_card),
        )

        visible_blockers = stats_service.recent_blockers(
            user_id=self.user_id,
            include_archived=False,
        )
        visible_links = stats_service.recent_knowledge_links(
            user_id=self.user_id,
            include_archived=False,
        )
        self.assertEqual([row["blockers"] for row in visible_blockers], ["当前卡点"])
        self.assertEqual(visible_links, [])

    def test_archived_course_invalidates_persisted_daily_ai_plan_and_grading(self):
        course = self._create_course("当天归档课程")
        knowledge_id = self._seed_knowledge(course["id"], "当天计划知识点", mastery=30)
        plan = {
            "main_line": "检查当天知识点。",
            "questions": [
                {
                    "question_id": "q1",
                    "knowledge_id": knowledge_id,
                    "topic": "当天计划知识点",
                    "question_type": "快速定位题",
                    "question": "请解释这个知识点。",
                    "answer_format": "用一句话回答。",
                    "expected_points": ["核心逻辑"],
                }
            ],
        }
        snapshot = [{"knowledge_id": knowledge_id, "topic": "当天计划知识点"}]
        plan_id = db.insert_and_get_id(
            """
            INSERT INTO daily_ai_review_plans (
                user_id, review_date, plan_json, source_snapshot_json, status
            ) VALUES (?, ?, ?, ?, '待回答')
            """,
            (
                self.user_id,
                date.today().isoformat(),
                json.dumps(plan, ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )
        stale_plan = daily_ai_review_service.get_today_ai_review_plan(
            user_id=self.user_id
        )
        self.assertEqual(stale_plan["id"], plan_id)

        course_service.archive_course(self.user_id, course["id"])

        self.assertIsNone(
            daily_ai_review_service.get_today_ai_review_plan(user_id=self.user_id)
        )
        with patch.object(
            daily_ai_review_service,
            "generate_text",
            side_effect=AssertionError("归档计划不应再调用模型"),
        ):
            with self.assertRaisesRegex(ValueError, "归档"):
                daily_ai_review_service.evaluate_today_ai_review(
                    plan_row=stale_plan,
                    answers={"q1": "回答"},
                    provider_key="test-provider",
                    api_key="test-key",
                    model="test-model",
                )
        self.assertEqual(
            db.fetch_one(
                "SELECT mastery FROM knowledge_cards WHERE id = ?",
                (knowledge_id,),
            )["mastery"],
            30,
        )

    def test_ai_grading_rejects_plan_replaced_during_model_call(self):
        course = self._create_course("并发自测课程")
        stale_card_id = self._seed_knowledge(course["id"], "旧计划知识点", mastery=30)
        current_card_id = self._seed_knowledge(course["id"], "新计划知识点", mastery=45)
        stale_plan = {
            "main_line": "旧计划",
            "questions": [
                {
                    "question_id": "old-q1",
                    "knowledge_id": stale_card_id,
                    "topic": "旧计划知识点",
                }
            ],
        }
        current_plan = {
            "main_line": "新计划",
            "questions": [
                {
                    "question_id": "new-q1",
                    "knowledge_id": current_card_id,
                    "topic": "新计划知识点",
                }
            ],
        }
        stale_snapshot_json = json.dumps(
            [{"knowledge_id": stale_card_id, "topic": "旧计划知识点"}],
            ensure_ascii=False,
        )
        current_plan_json = json.dumps(current_plan, ensure_ascii=False)
        current_snapshot_json = json.dumps(
            [{"knowledge_id": current_card_id, "topic": "新计划知识点"}],
            ensure_ascii=False,
        )
        plan_id = db.insert_and_get_id(
            """
            INSERT INTO daily_ai_review_plans (
                user_id, review_date, plan_json, source_snapshot_json, status
            ) VALUES (?, ?, ?, ?, '待回答')
            """,
            (
                self.user_id,
                date.today().isoformat(),
                current_plan_json,
                current_snapshot_json,
            ),
        )
        stale_evaluation = {
            "overall_summary": "旧批改结果",
            "evaluations": [
                {
                    "question_id": "old-q1",
                    "knowledge_id": stale_card_id,
                    "score": 100,
                    "result": "完全掌握",
                    "cause_category": "",
                    "feedback": "",
                    "correct_answer": "",
                    "next_question": "",
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "计划已更新"):
            daily_ai_review_service._apply_evaluation_results(
                stale_plan,
                stale_evaluation,
                answers={"old-q1": "旧回答"},
                plan_id=plan_id,
                user_id=self.user_id,
                expected_plan_json=json.dumps(stale_plan, ensure_ascii=False),
                expected_source_snapshot_json=stale_snapshot_json,
            )

        mastery_rows = db.fetch_all(
            "SELECT id, mastery FROM knowledge_cards WHERE id IN (?, ?) ORDER BY id",
            (stale_card_id, current_card_id),
        )
        self.assertEqual([row["mastery"] for row in mastery_rows], [30, 45])
        stored_plan = db.fetch_one(
            "SELECT plan_json, source_snapshot_json, status FROM daily_ai_review_plans WHERE id = ?",
            (plan_id,),
        )
        self.assertEqual(stored_plan["plan_json"], current_plan_json)
        self.assertEqual(stored_plan["source_snapshot_json"], current_snapshot_json)
        self.assertEqual(stored_plan["status"], "待回答")

    def test_dashboard_current_course_prefers_the_active_reader_context(self):
        earlier = self._create_course("正在阅读的课程")
        earlier_deck_id, _ = self._seed_deck(earlier["id"], "当前课件")
        later = self._create_course("较新但未在学习的课程")
        set_active_deck(self.user_id, earlier_deck_id)

        snapshot = course_service.get_dashboard_snapshot(self.user_id)

        self.assertEqual(snapshot["current_course"]["id"], earlier["id"])
        self.assertNotEqual(snapshot["current_course"]["id"], later["id"])

    def test_completed_and_archived_course_details_remain_readable(self):
        completed = self._create_course("C 语言程序设计")
        archived = self._create_course("工程伦理")
        completed_deck_id, _ = self._seed_deck(
            completed["id"],
            "指针与内存",
            slide_count=1,
        )
        archived_deck_id, _ = self._seed_deck(
            archived["id"],
            "责任与规范",
            slide_count=1,
        )
        course_service.complete_course(self.user_id, completed["id"])
        course_service.archive_course(self.user_id, archived["id"])

        completed_detail = course_service.get_course_detail(self.user_id, completed["id"])
        archived_detail = course_service.get_course_detail(self.user_id, archived["id"])

        self.assertEqual(completed_detail["course"]["status"], "completed")
        self.assertEqual(archived_detail["course"]["status"], "archived")
        self.assertEqual(
            {deck["id"] for deck in completed_detail["decks"]},
            {completed_deck_id},
        )
        self.assertEqual(
            {deck["id"] for deck in archived_detail["decks"]},
            {archived_deck_id},
        )
        self.assertIsNotNone(completed_detail["summary"])
        self.assertIn("learning_phases", completed_detail)
        self.assertIn("learning_phases", archived_detail)


if __name__ == "__main__":
    unittest.main()
