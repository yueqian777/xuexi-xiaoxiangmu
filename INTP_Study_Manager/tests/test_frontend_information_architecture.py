import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


class FrontendInformationArchitectureTest(unittest.TestCase):
    def test_dashboard_is_today_workbench(self):
        source = _source("pages/dashboard.py")

        self.assertIn("今日工作台", source)
        self.assertIn("继续资料学习", source)
        self.assertIn("常用行动入口", source)

    def test_ppt_tutor_exposes_workbench_modes(self):
        source = _source("pages/ppt_tutor.py")

        for label in ["阅读", "资料准备", "生成讲解", "学习沉淀"]:
            self.assertIn(label, source)
        self.assertIn("ppt_workbench_mode", source)

    def test_api_settings_exposes_task_modes(self):
        source = _source("pages/api_settings.py")

        for label in ["日常调用", "密钥库", "Provider 管理", "余额 / Plan", "参考"]:
            self.assertIn(label, source)
        self.assertIn("api_settings_mode", source)

    def test_knowledge_cards_is_browse_first(self):
        source = _source("pages/knowledge_cards.py")

        self.assertIn("知识沉淀工作台", source)
        self.assertIn("浏览知识点", source)
        self.assertIn("新建知识点", source)
        self.assertIn("知识双链", source)


if __name__ == "__main__":
    unittest.main()
