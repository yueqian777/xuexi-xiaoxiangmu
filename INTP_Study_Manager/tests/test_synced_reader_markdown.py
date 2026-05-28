import os
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
READER_HTML = APP_ROOT / "components" / "synced_reader" / "index.html"


def _extract_function(source, name):
    marker = f"function {name}("
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
            "findMathSegmentAt",
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
            "displayExplanationSourceInfo",
            "displayExplanationSource",
            "findMathSegmentBoundsForLocation",
            "appendSearchableChar",
            "appendSearchableRange",
            "commonSuffixLength",
            "commonPrefixLength",
            "meaningfulContextLength",
            "trustedMarkdownSelectionLocation",
            "locateMarkdownSelectionInSource",
            "displayAwareMarkdownSelectionLocation",
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

    def test_can_highlight_inline_math_by_visible_formula_text(self):
        self.run_js(
            r"""
            const source = 'Formula $x = y + z$ after.';
            const payload = {
              selectedText: 'x = y + z',
              selectedTextRaw: 'x = y + z',
              contextBefore: 'Formula ',
              contextAfter: ' after.',
              selectionStartOffset: 'Formula '.length,
            };
            const result = wrapMarkdownSelection(source, payload);
            if (!result || result.action !== 'add') {
              throw new Error(JSON.stringify(result));
            }
            if (result.source !== 'Formula ==$x = y + z$== after.') {
              throw new Error(result.source);
            }
            """
        )

    def test_repeated_inline_math_highlights_selected_occurrence(self):
        self.run_js(
            r"""
            const source = 'First $x=1$ middle $x=1$ end.';
            const payload = {
              selectedText: 'x=1',
              selectedTextRaw: 'x=1',
              contextBefore: 'First x=1 middle ',
              contextAfter: ' end.',
              selectionStartOffset: 'First x=1 middle '.length,
            };
            const result = wrapMarkdownSelection(source, payload);
            if (!result || result.action !== 'add') {
              throw new Error(JSON.stringify(result));
            }
            if (result.source !== 'First $x=1$ middle ==$x=1$== end.') {
              throw new Error(result.source);
            }
            """
        )

    def test_hidden_preamble_does_not_shift_repeated_highlight_target(self):
        self.run_js(
            r"""
            const source = '[[\u7b2c 1 \u9875]] [[\u6807\u7b7e:\u8bb2\u89e3\u9875]]: repeat\n\nA repeat B repeat C';
            const payload = {
              selectedText: 'repeat',
              selectedTextRaw: 'repeat',
              contextBefore: 'A repeat B ',
              contextAfter: ' C',
              selectionStartOffset: 'A repeat B '.length,
            };
            const result = wrapMarkdownSelection(source, payload);
            if (!result || result.action !== 'add') {
              throw new Error(JSON.stringify(result));
            }
            const expected = '[[\u7b2c 1 \u9875]] [[\u6807\u7b7e:\u8bb2\u89e3\u9875]]: repeat\n\nA repeat B ==repeat== C';
            if (result.source !== expected) {
              throw new Error(result.source);
            }
            """
        )

    def test_repeated_text_after_math_uses_nearby_context_over_offset(self):
        self.run_js(
            r"""
            const source = [
              '\u5982\u679c f(t) \u662f\u5468\u671f\u4e3a T \u7684\u5468\u671f\u4fe1\u53f7\uff0c\u5219\u6ee1\u8db3\u57fa\u672c\u5b9a\u4e49\u3002',
              '',
              '$$',
              '\\text{MathJax rendered text can differ from this very long TeX source }',
              '\\quad a_1 + a_2 + a_3 + a_4 + a_5 + a_6 + a_7 + a_8 + a_9',
              '$$',
              '',
              '- \u548c\u524d\u7f6e\u6982\u5ff5 \u5468\u671f\u4fe1\u53f7 \u76f4\u63a5\u76f8\u5173\uff0c\u7528\u4e8e\u5224\u65ad\u7cfb\u7edf\u7a33\u5b9a\u6027\u3002',
            ].join('\n');
            const payload = {
              selectedText: '\u5468\u671f\u4fe1\u53f7',
              selectedTextRaw: '\u5468\u671f\u4fe1\u53f7',
              contextBefore: '\u5982\u679c f(t) \u662f\u5468\u671f\u4e3a T \u7684\u5468\u671f\u4fe1\u53f7\u3002 \u548c\u524d\u7f6e\u6982\u5ff5 ',
              contextAfter: ' \u76f4\u63a5\u76f8\u5173\uff0c\u7528\u4e8e\u5224\u65ad\u7cfb\u7edf\u7a33\u5b9a\u6027\u3002',
              selectionStartOffset: '\u5982\u679c f(t) \u662f\u5468\u671f\u4e3a T \u7684\u5468\u671f\u4fe1\u53f7\u3002 \u548c\u524d\u7f6e\u6982\u5ff5 '.length,
            };
            const result = wrapMarkdownSelection(source, payload);
            if (!result || result.action !== 'add') {
              throw new Error(JSON.stringify(result));
            }
            const expected = source.replace(
              '- \u548c\u524d\u7f6e\u6982\u5ff5 \u5468\u671f\u4fe1\u53f7 \u76f4\u63a5\u76f8\u5173',
              '- \u548c\u524d\u7f6e\u6982\u5ff5 ==\u5468\u671f\u4fe1\u53f7== \u76f4\u63a5\u76f8\u5173'
            );
            if (result.source !== expected) {
              throw new Error(result.source);
            }
          """
        )

    def test_repeated_text_uses_source_range_when_context_is_weak(self):
        self.run_js(
            r"""
            const source = [
              '\u4e0a\u65b9\uff1a\u5468\u671f\u4fe1\u53f7',
              '',
              '$$ a_1 + a_2 + a_3 + a_4 + a_5 + a_6 + a_7 + a_8 $$',
              '',
              '\u4e0b\u65b9\uff1a\u5468\u671f\u4fe1\u53f7',
            ].join('\n');
            const lowerStart = source.lastIndexOf('\u5468\u671f\u4fe1\u53f7');
            const payload = {
              selectedText: '\u5468\u671f\u4fe1\u53f7',
              selectedTextRaw: '\u5468\u671f\u4fe1\u53f7',
              contextBefore: '',
              contextAfter: '',
              selectionStartOffset: 0,
              sourceStart: lowerStart,
              sourceEnd: lowerStart + '\u5468\u671f\u4fe1\u53f7'.length,
            };
            const result = wrapMarkdownSelection(source, payload);
            if (!result || result.action !== 'add') {
              throw new Error(JSON.stringify(result));
            }
            const expected = source.replace(
              '\u4e0b\u65b9\uff1a\u5468\u671f\u4fe1\u53f7',
              '\u4e0b\u65b9\uff1a==\u5468\u671f\u4fe1\u53f7=='
            );
            if (result.source !== expected) {
              throw new Error(result.source);
            }
            """
        )

    def test_render_markdown_highlights_math_segment(self):
        self.run_js(
            r"""
            global.window = {};

            const rendered = renderMarkdown('Formula ==$x = y + z$== after.');
            if (!rendered.includes('<mark class="reader-highlight">')) {
              throw new Error(rendered);
            }
            if (!rendered.includes('\\(x = y + z\\)')) {
              throw new Error(rendered);
            }
            if (rendered.includes('MATHJAXPLACEHOLDER')) {
              throw new Error(rendered);
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
