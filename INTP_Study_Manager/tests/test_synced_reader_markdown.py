import os
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
READER_HTML = APP_ROOT / "components" / "synced_reader" / "index.html"


def _extract_function(source, name):
    marker = f"function {name}"
    start = source.find(marker)
    if start < 0:
        return ""
    brace_start = source.find("{", start)
    if brace_start < 0:
        return ""
    depth = 0
    for index in range(brace_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    return ""


def _node_executable():
    candidates = [
        os.environ.get("NODE"),
        shutil.which("node"),
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            result = subprocess.run(
                [str(candidate), "--version"],
                cwd=APP_ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=5,
            )
        except OSError:
            continue
        if result.returncode == 0:
            return str(candidate)
    return None


class SyncedReaderMarkdownTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = _node_executable()
        if not cls.node:
            raise unittest.SkipTest("Node.js is not available for synced-reader JS tests")
        source = READER_HTML.read_text(encoding="utf-8")
        helper_names = [
            "escapeHtml",
            "findUnescaped",
            "isAsciiWordLike",
            "isLikelyEqualityOperator",
            "findHighlightDelimiter",
            "normalizeMathDelimiters",
            "protectMathSegments",
            "restoreMathSegments",
            "protectMarkdownCodeSegments",
            "restoreMarkdownCodeSegments",
            "protectHighlightSegments",
            "restoreHighlightSegments",
            "renderFallbackCodeSegment",
            "renderFallbackMarkdown",
            "renderMarkdown",
            "isGeneratedExplanationPreambleLine",
            "displayExplanationSource",
            "markdownSearchText",
            "collapsedSearchText",
            "locateMarkdownSelection",
            "markdownHighlightBounds",
            "markdownSelectionHighlightState",
            "removeMarkdownHighlight",
            "wrapMarkdownSelection",
        ]
        cls.js_helpers = "\n\n".join(
            block for name in helper_names if (block := _extract_function(source, name))
        )

    def run_js(self, body):
        script = self.js_helpers + "\n\n" + textwrap.dedent(body)
        result = subprocess.run(
            [self.node, "-e", script],
            cwd=APP_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_code_equality_is_not_markdown_highlighted(self):
        self.run_js(
            r"""
            global.window = {
              marked: { parse: value => String(value) },
              DOMPurify: { sanitize: value => String(value) },
            };

            const rendered = renderMarkdown('判断 `pow == 128` 后，再判断 `x == 1`。');
            if (rendered.includes('reader-highlight')) {
              throw new Error(rendered);
            }
            if (!rendered.includes('pow == 128') || !rendered.includes('x == 1')) {
              throw new Error(rendered);
            }
            """
        )

    def test_plain_equality_is_not_markdown_highlighted(self):
        self.run_js(
            r"""
            global.window = {
              marked: { parse: value => String(value) },
              DOMPurify: { sanitize: value => String(value) },
            };

            const rendered = renderMarkdown('也就是 pow == 128 时退出循环，随后 sum==target，再判断 x == 7。');
            if (rendered.includes('reader-highlight')) {
              throw new Error(rendered);
            }
            if (!rendered.includes('pow == 128') || !rendered.includes('sum==target') || !rendered.includes('x == 7')) {
              throw new Error(rendered);
            }
            """
        )

    def test_fallback_renderer_preserves_fenced_code_blocks(self):
        self.run_js(
            r"""
            global.window = {};

            const rendered = renderMarkdown('```c\nwhile (pow != 128) {\n  pow = pow * 2;\n  x = x + 1;\n}\n```');
            if (!rendered.includes('<pre><code') || rendered.includes('```')) {
              throw new Error(rendered);
            }
            if (!rendered.includes('pow = pow * 2;')) {
              throw new Error(rendered);
            }
            """
        )

    def test_can_remove_highlight_around_equality_expression(self):
        self.run_js(
            r"""
            const source = '说明：==pow == 128== 时退出循环';
            const payload = {
              selectedText: 'pow == 128',
              selectedTextRaw: 'pow == 128',
              contextBefore: '说明：',
              contextAfter: ' 时退出循环',
              selectionStartOffset: 3,
            };
            const state = markdownSelectionHighlightState(source, payload);
            if (!state.isHighlighted) {
              throw new Error(JSON.stringify(state));
            }
            const result = wrapMarkdownSelection(source, payload);
            if (!result || result.action !== 'remove' || result.source !== '说明：pow == 128 时退出循环') {
              throw new Error(JSON.stringify(result));
            }
            """
        )

    def test_display_explanation_strips_generated_wikilink_preamble(self):
        self.run_js(
            r"""
            const source = '[[\u7b2c 1 \u9875]] [[\u6807\u7b7e:\u8bb2\u89e3\u9875]]: \u4ece\u8f93\u5165\u8f93\u51fa\u63cf\u8ff0\u5207\u5165\u72b6\u6001\u53d8\u91cf\u5206\u6790\n\n### \u672c\u9875\u6838\u5fc3\n- \u7cfb\u7edf\u63cf\u8ff0\u65b9\u6cd5';
            const result = displayExplanationSource(source);
            if (result.includes('[[\u7b2c 1 \u9875]]') || result.includes('[[\u6807\u7b7e:')) {
              throw new Error(result);
            }
            if (!result.startsWith('### \u672c\u9875\u6838\u5fc3')) {
              throw new Error(result);
            }
            """
        )

    def test_rendered_note_header_does_not_include_bilink_controls(self):
        source = READER_HTML.read_text(encoding="utf-8")
        self.assertNotIn('<span class="note-links">', source)
        self.assertNotIn("renderNoteBiLinks(page)", source)


if __name__ == "__main__":
    unittest.main()
