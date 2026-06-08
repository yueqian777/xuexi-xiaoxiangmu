import unittest

from pages import ppt_explanation_export


class PptExplanationExportPageCopyTest(unittest.TestCase):
    def test_copy_explains_multi_select_and_public_boundary(self):
        copy = ppt_explanation_export.get_ppt_share_export_copy()

        self.assertEqual(copy["deck_label"], "选择要打包的 PPT / PDF（可多选）")
        self.assertIn("只给别人看 PPT 页面、页面图片和 AI 逐页讲解", copy["boundary"])
        self.assertIn("不会导出你的学习记录", copy["boundary"])
        self.assertEqual(copy["button"], "生成公开分享 ZIP")
        self.assertIn("默认关闭", copy["include_original_label"])

    def test_privacy_exclusion_labels_are_readable(self):
        labels = ppt_explanation_export.PUBLIC_EXCLUDED_SECTION_LABELS

        self.assertEqual(labels["slide_questions"], "PPT 页面的插问和追问")
        self.assertEqual(labels["api_keys"], "API Key 和密钥文件")
        self.assertNotEqual(labels["knowledge_cards"], "knowledge_cards")


if __name__ == "__main__":
    unittest.main()
