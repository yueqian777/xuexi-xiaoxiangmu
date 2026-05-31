import unittest

from pages import ppt_tutor
from services.pdf_extraction_service import MinerUStatus


class PptPdfExtractionOptionsTest(unittest.TestCase):
    def test_mineru_option_is_not_selectable_when_unavailable(self):
        options = ppt_tutor._pdf_extraction_method_options(
            MinerUStatus(available=False, command="", message="MinerU 未安装")
        )

        self.assertEqual([value for value, _label in options], ["local"])

    def test_mineru_option_is_selectable_when_available(self):
        options = ppt_tutor._pdf_extraction_method_options(
            MinerUStatus(available=True, command="D:\\MinerU\\.venv\\Scripts\\mineru.exe", message="可用")
        )

        self.assertEqual([value for value, _label in options], ["local", "mineru"])


if __name__ == "__main__":
    unittest.main()
