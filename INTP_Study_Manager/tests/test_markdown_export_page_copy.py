import unittest

from pages import markdown_export


class MarkdownExportPageCopyTest(unittest.TestCase):
    def test_private_export_copy_explains_scope_modes_and_secret_boundary(self):
        copy = markdown_export.get_markdown_export_copy()

        self.assertEqual(copy["title"], "私人 Markdown / Obsidian 导出")
        self.assertEqual(copy["subject_label"], "导出哪些科目")
        self.assertEqual(copy["mode_label"], "遇到已存在的 Markdown 文件时怎么处理")
        self.assertEqual(copy["mode_options"]["incremental"], "增量导出（推荐）：只写新增或变化的文件")
        self.assertEqual(copy["mode_options"]["overwrite"], "覆盖重建：先清空导出目录再重新生成")
        self.assertEqual(copy["button"], "生成私人 Markdown 知识库")
        self.assertEqual(copy["success_template"], "已生成/更新 {files_written} 个 Markdown 文件")
        self.assertIn("私人 Markdown / Obsidian", copy["caption"])
        self.assertIn("个人学习资料", copy["info"])
        self.assertIn("API Key", copy["info"])
        self.assertIn("API provider", copy["info"])


if __name__ == "__main__":
    unittest.main()
