import ast
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
API_SETTINGS_SOURCE = APP_ROOT / "pages" / "api_settings.py"


class ApiSettingsPermissionsTest(unittest.TestCase):
    def test_provider_management_tabs_are_admin_only(self):
        tree = ast.parse(API_SETTINGS_SOURCE.read_text(encoding="utf-8"))
        render = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render")
        admin_branch = next(
            node
            for node in ast.walk(render)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and ast.unparse(node.test) == "user.role == 'admin'"
        )
        admin_text = "\n".join(ast.unparse(node) for node in admin_branch.body)
        user_text = "\n".join(ast.unparse(node) for node in admin_branch.orelse)

        self.assertIn("_render_provider_management", admin_text)
        self.assertIn("_render_balance_query", admin_text)
        self.assertIn("_render_edit_provider", admin_text)
        self.assertIn("_render_create_provider", admin_text)
        self.assertNotIn("_render_provider_management", user_text)
        self.assertNotIn("_render_edit_provider", user_text)
        self.assertNotIn("_render_create_provider", user_text)


if __name__ == "__main__":
    unittest.main()
