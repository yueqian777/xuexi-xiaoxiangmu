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
        cls.render_upload_form = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_render_upload_form"
        )
        cls.source_page_editor = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_render_source_page_editor"
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

    def test_manual_source_page_editor_replaces_auto_rescan_actions(self):
        action_constants = {
            item.value
            for item in ast.walk(self.render_deck_actions)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        nested_calls = {_call_name(item) for item in ast.walk(self.render_deck_actions) if isinstance(item, ast.Call)}

        self.assertIn("_render_source_page_editor", nested_calls)
        self.assertNotIn("重新扫描 / 补齐 PDF 页面", action_constants)
        self.assertNotIn("重新扫描 / 补齐 PPT 页面", action_constants)

    def test_manual_source_page_editor_supports_page_insert_replace_and_delete(self):
        constants = {
            item.value
            for item in ast.walk(self.source_page_editor)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        nested_calls = {_call_name(item) for item in ast.walk(self.source_page_editor) if isinstance(item, ast.Call)}

        self.assertIn("从另一个 PPT / PDF 插入、替换或删除单页", constants)
        self.assertIn("选择包含目标页面的 PPTX 或 PDF 文件", constants)
        self.assertIn("解析来源文件", constants)
        self.assertIn("插入到目标页前", constants)
        self.assertIn("替换目标页", constants)
        self.assertIn("删除当前已有页面", constants)
        self.assertIn("应用到当前资料", constants)
        self.assertIn("不会删除已有讲解和查问；替换只换页面内容。", constants)
        self.assertIn("删除会移除该页讲解和查问，后面的页码自动前移。", constants)
        self.assertIn("save_page_source_file", nested_calls)
        self.assertIn("extract_source_pages", nested_calls)
        self.assertIn("apply_source_page_to_deck", nested_calls)
        self.assertIn("delete_deck_page", nested_calls)

    def test_animation_state_generation_hooks_are_exposed(self):
        action_constants = {
            item.value
            for item in ast.walk(self.render_deck_actions)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        action_calls = {_call_name(item) for item in ast.walk(self.render_deck_actions) if isinstance(item, ast.Call)}
        upload_calls = {_call_name(item) for item in ast.walk(self.render_upload_form) if isinstance(item, ast.Call)}

        self.assertIn("生成 / 修复动画状态", action_constants)
        self.assertIn("_generate_deck_animation_states_best_effort", action_calls)
        self.assertIn("_generate_deck_animation_states_best_effort", upload_calls)


if __name__ == "__main__":
    unittest.main()
