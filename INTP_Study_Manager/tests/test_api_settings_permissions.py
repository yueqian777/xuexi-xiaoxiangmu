import ast
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
API_SETTINGS_SOURCE = APP_ROOT / "pages" / "api_settings.py"


class ApiSettingsPermissionsTest(unittest.TestCase):
    def test_provider_management_modes_are_admin_only(self):
        tree = ast.parse(API_SETTINGS_SOURCE.read_text(encoding="utf-8"))
        render = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render")
        non_admin_branch = next(
            node
            for node in ast.walk(render)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and ast.unparse(node.test) == "user.role != 'admin'"
        )
        non_admin_text = "\n".join(ast.unparse(node) for node in non_admin_branch.body)
        render_text = ast.unparse(render)

        self.assertIn("'Provider 管理'", render_text)
        self.assertIn("'余额 / Plan'", render_text)
        self.assertIn("mode == 'Provider 管理' and user.role == 'admin'", render_text)
        self.assertIn("mode == '余额 / Plan' and user.role == 'admin'", render_text)
        self.assertIn("modes = ['日常调用', '密钥库', '参考']", non_admin_text)
        self.assertNotIn("'Provider 管理'", non_admin_text)
        self.assertNotIn("'余额 / Plan'", non_admin_text)


if __name__ == "__main__":
    unittest.main()
