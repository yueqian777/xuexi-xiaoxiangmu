import ast
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PPT_TUTOR_SOURCE = APP_ROOT / "pages" / "ppt_tutor.py"


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _first_string_arg(node: ast.Call) -> str:
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return ""


def _string_keyword(node: ast.Call, keyword_name: str) -> str:
    keyword = next((item for item in node.keywords if item.arg == keyword_name), None)
    if keyword and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
        return keyword.value.value
    return ""


class PptTutorGenerationControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(PPT_TUTOR_SOURCE.read_text(encoding="utf-8"))
        cls.render_deck_actions = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_render_deck_actions"
        )

    def test_generation_controls_are_inside_collapsed_expander(self):
        expander = None
        for node in ast.walk(self.render_deck_actions):
            if not isinstance(node, ast.With):
                continue
            for item in node.items:
                context_expr = item.context_expr
                if isinstance(context_expr, ast.Call) and _call_name(context_expr) == "st.expander":
                    if _first_string_arg(context_expr) == "逐页讲解生成配置":
                        expander = node
                        expanded_kw = next(
                            (kw for kw in context_expr.keywords if kw.arg == "expanded"),
                            None,
                        )
                        self.assertIsNotNone(expanded_kw)
                        self.assertIsInstance(expanded_kw.value, ast.Constant)
                        self.assertIs(expanded_kw.value.value, False)
                        break
            if expander:
                break

        self.assertIsNotNone(expander)
        nested_calls = {_call_name(item) for item in ast.walk(expander) if isinstance(item, ast.Call)}
        constants = {
            item.value
            for item in ast.walk(expander)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        self.assertIn("_select_generation_range", nested_calls)
        self.assertIn("本次生成使用的 API 组", constants)
        self.assertIn("生成所选范围逐页讲解", constants)

    def test_parallelism_explanations_are_in_adaptive_help_not_captions(self):
        retry_text = "生成出错的页面会自动重新加入队列，直到本次范围内可生成页面全部成功。"
        sync_text = "左侧滚动到某页时，右侧讲解会自动同步滚动到对应页。"
        adaptive_checkbox = next(
            node
            for node in ast.walk(self.render_deck_actions)
            if isinstance(node, ast.Call)
            and _call_name(node).endswith(".checkbox")
            and _first_string_arg(node) == "自适应最快速度"
        )

        help_text = _string_keyword(adaptive_checkbox, "help")
        self.assertIn(retry_text, help_text)
        self.assertIn(sync_text, help_text)

        visible_captions = {
            _first_string_arg(node)
            for node in ast.walk(self.render_deck_actions)
            if isinstance(node, ast.Call) and _call_name(node).endswith(".caption")
        }
        self.assertNotIn(retry_text, visible_captions)
        self.assertNotIn(sync_text, visible_captions)


if __name__ == "__main__":
    unittest.main()
