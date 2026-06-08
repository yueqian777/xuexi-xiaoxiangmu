import os
import re
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
            "clamp",
            "findUnescaped",
            "isAsciiWordLike",
            "isLikelyEqualityOperator",
            "findHighlightDelimiter",
            "isEscapedAt",
            "dollarRunLength",
            "findDollarRun",
            "mathLineEnd",
            "looksLikeLatexSource",
            "repairSplitLeftRightMathSegments",
            "normalizeDollarMathDelimiters",
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
            "renderSafeExplanationMarkdown",
            "noteDisplayMarkdown",
            "applyPendingExplanationOverrides",
            "isGeneratedExplanationPreambleLine",
            "displayExplanationSourceInfo",
            "displayExplanationSource",
            "pageForSlide",
            "createComponentToken",
            "initialReaderTargetSlide",
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
            "quoteLocationForCentering",
            "searchLocationForRawLocation",
            "centeredScrollTopForElement",
            "shouldRestoreStoredPageScroll",
            "suppressReaderObserver",
            "scheduleProgrammaticScrollStateSave",
            "questionIdForItem",
            "removeMarkdownHighlight",
            "wrapMarkdownSelection",
            "renderChatQuestion",
            "renderChatTurn",
            "renderQuestionThread",
            "scrollChatQuestionToTop",
            "isNearChatBottom",
            "setChatBottomButtonVisible",
            "updateChatBottomButton",
            "bottomButtonForChatPanel",
            "updateChatBottomButtons",
            "clipText",
            "nodeElement",
            "rectFromRange",
            "globalStorageKey",
            "loadLayoutState",
            "applyReaderWidthClass",
            "applyLayoutState",
            "applyReaderLayoutChangeWithAnchors",
            "openCanvasChat",
            "toggleCanvasChat",
            "scrollAnchorCandidates",
            "visualRectForAnchor",
            "cssAttributeValue",
            "stableScrollAnchorSelector",
            "measurableRangeForCaret",
            "captureTextRangeAnchor",
            "broadScrollAnchorPenalty",
            "shouldCaptureTextRangeAnchor",
            "setPanelScroll",
            "captureScrollPanelAnchor",
            "restoreScrollPanelAnchor",
            "captureReaderViewportAnchors",
            "restoreReaderViewportAnchors",
            "restoreReaderAnchorsAfterLayoutChange",
            "updateResize",
            "nearestScrollPanel",
            "scrollChildPanelToQuestionTop",
            "childLayerScrollPositions",
            "renderChildQuestionStack",
            "sendQuestionClose",
            "closeChildLayersForSlideChange",
            "openChildChatFromQuote",
            "closeChildLayer",
            "bookmarkTitleForPage",
            "bookmarkedPages",
            "renderBookmarkIcon",
            "renderBookmarkList",
            "renderBookmarkPanel",
            "updateBookmarkControls",
            "updatePageBookmarkButton",
            "sendBookmarkUpdate",
            "togglePageBookmark",
            "renameBookmark",
            "jumpToBookmark",
            "closeBookmarkPanel",
            "toggleBookmarkPanel",
            "setActive",
        ]
        cls.js_helpers = "\n\n".join(
            block for name in helper_names if (block := _extract_function(source, name))
        )

    def run_js(self, body):
        script = self.js_helpers + "\n\n" + textwrap.dedent(body)
        result = subprocess.run(
            [self.node, "-"],
            cwd=APP_ROOT,
            input=script,
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

    def test_quote_centering_uses_source_range_for_repeated_text(self):
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
            const location = quoteLocationForCentering(source, payload);
            if (!location || location.start !== lowerStart || location.end !== payload.sourceEnd) {
              throw new Error(JSON.stringify(location));
            }
            """
        )

    def test_raw_source_location_maps_to_rendered_search_range_after_hidden_preamble(self):
        self.run_js(
            r"""
            const source = [
              '[[\u7b2c 1 \u9875]] [[\u6807\u7b7e:\u8bb2\u89e3\u9875]]: \u5468\u671f\u4fe1\u53f7',
              '',
              '\u4e0a\u65b9\uff1a\u5468\u671f\u4fe1\u53f7',
              '',
              '\u4e0b\u65b9\uff1a\u5468\u671f\u4fe1\u53f7',
            ].join('\n');
            const lowerStart = source.lastIndexOf('\u5468\u671f\u4fe1\u53f7');
            const info = displayExplanationSourceInfo(source);
            const searchable = markdownSearchText(info.displaySource);
            const location = searchLocationForRawLocation(searchable, info.displayToRaw, {
              start: lowerStart,
              end: lowerStart + '\u5468\u671f\u4fe1\u53f7'.length,
            });
            if (!location) {
              throw new Error('missing search location');
            }
            const selected = searchable.text.slice(location.start, location.end);
            if (selected !== '\u5468\u671f\u4fe1\u53f7') {
              throw new Error(JSON.stringify({ location, selected, text: searchable.text }));
            }
            const before = searchable.text.slice(0, location.start);
            if (!before.includes('\u4e0b\u65b9\uff1a')) {
              throw new Error(JSON.stringify({ location, before, text: searchable.text }));
            }
            """
        )

    def test_centered_scroll_top_clamps_to_scroll_bounds(self):
        self.run_js(
            r"""
            const centered = centeredScrollTopForElement(400, 900, 50, 1200);
            if (centered !== 725) {
              throw new Error(String(centered));
            }
            const clampedStart = centeredScrollTopForElement(400, 40, 40, 1200);
            if (clampedStart !== 0) {
              throw new Error(String(clampedStart));
            }
            const clampedEnd = centeredScrollTopForElement(400, 1500, 80, 1200);
            if (clampedEnd !== 1200) {
              throw new Error(String(clampedEnd));
            }
            """
        )

    def test_page_scroll_restores_only_during_same_deck_refresh(self):
        self.run_js(
            r"""
            if (shouldRestoreStoredPageScroll(false, true) !== false) {
              throw new Error('first entry must center the target slide');
            }
            if (shouldRestoreStoredPageScroll(true, true) !== true) {
              throw new Error('same deck refresh should preserve reading position');
            }
            if (shouldRestoreStoredPageScroll(true, false) !== false) {
              throw new Error('target mismatch should not restore stale scroll');
            }
            """
        )

    def test_suppress_reader_observer_extends_existing_window(self):
        self.run_js(
            r"""
            const originalNow = Date.now;
            const VIEWPORT_ANCHOR_MS = 1400;
            let suppressObserverUntil = 5000;
            Date.now = () => 1000;
            suppressReaderObserver(200);
            if (suppressObserverUntil !== 5000) {
              throw new Error(String(suppressObserverUntil));
            }
            suppressReaderObserver(7000);
            if (suppressObserverUntil !== 8000) {
              throw new Error(String(suppressObserverUntil));
            }
            Date.now = originalNow;
            """
        )

    def test_programmatic_scroll_save_delays_smooth_scroll_position(self):
        self.run_js(
            r"""
            let currentSlideSaved = false;
            let scheduledDelay = null;
            function saveCurrentSlideState() { currentSlideSaved = true; }
            function scheduleScrollStateSave(delayMs) { scheduledDelay = delayMs; }

            scheduleProgrammaticScrollStateSave('smooth');
            if (!currentSlideSaved || scheduledDelay < 600) {
              throw new Error(JSON.stringify({ currentSlideSaved, scheduledDelay }));
            }

            currentSlideSaved = false;
            scheduledDelay = null;
            scheduleProgrammaticScrollStateSave('auto');
            if (!currentSlideSaved || scheduledDelay > 250) {
              throw new Error(JSON.stringify({ currentSlideSaved, scheduledDelay }));
            }
            """
        )

    def test_initial_reader_target_uses_browser_saved_slide_only_without_backend_initial(self):
        self.run_js(
            r"""
            var pages = [
              { slideNumber: 1 },
              { slideNumber: 9 },
            ];
            var restoreScrollAfterRender = { currentSlide: 4 };

            const target = initialReaderTargetSlide(
              { initial_slide_number: 4 },
              { currentSlide: 9, pageScroll: 500, noteScroll: 300 },
              false
            );
            if (target !== 9) {
              throw new Error(String(target));
            }
            """
        )

    def test_set_active_hydrates_the_selected_note_immediately(self):
        self.run_js(
            r"""
            var pages = [{ slideNumber: 5 }];
            var currentSlideNumber = 1;
            var noteRoot = {
              offsetTop: 0,
              scrollTo(value) { this.lastScroll = value; },
            };
            const body = { dataset: { hydrated: '0' } };
            const page = {
              classList: {
                add(name) { this.added = name; },
                contains() { return false; },
                remove() {},
              },
            };
            const note = {
              offsetTop: 120,
              classList: {
                add(name) { this.added = name; },
                contains() { return false; },
                remove() {},
              },
              querySelector(selector) {
                return selector === '.note-body' ? body : null;
              },
            };
            var document = {
              getElementById(id) {
                if (id === 'page-5') return page;
                if (id === 'note-5') return note;
                return null;
              },
              querySelectorAll() { return []; },
            };
            var hydratedSlide = 0;
            var nearbySlide = 0;
            function closeChildLayersForSlideChange() {}
            function updatePageJumpDisplay() {}
            function updateSectionSelect() {}
            function renderChatForPage() {}
            function hydrateNote(slideNumber) {
              hydratedSlide = Number(slideNumber);
              body.dataset.hydrated = '1';
              return Promise.resolve(true);
            }
            function ensureNearbyContent(slideNumber) { nearbySlide = Number(slideNumber); }
            function scheduleNearbyContent(slideNumber) { nearbySlide = Number(slideNumber); }
            function updateRenderedPageImageWindow() {}
            function syncActivePageDom() {}
            function centerPage() {}
            function saveScrollState() {}
            function notifyReaderPosition() {}

            setActive(5, { scrollNote: false });
            if (hydratedSlide !== 5) {
              throw new Error(String(hydratedSlide));
            }
            if (nearbySlide !== 5) {
              throw new Error(String(nearbySlide));
            }
            """
        )

    def test_safe_explanation_markdown_falls_back_when_renderer_throws(self):
        self.run_js(
            r"""
            global.window = {};
            const originalRenderMarkdown = renderMarkdown;
            renderMarkdown = () => {
              throw new RangeError('Invalid string length');
            };

            const rendered = renderSafeExplanationMarkdown('### 标题\n\n公式 $x=1$');
            renderMarkdown = originalRenderMarkdown;

            if (!rendered.includes('标题') || !rendered.includes('$x=1$')) {
              throw new Error(rendered);
            }
            if (rendered.includes('<script')) {
              throw new Error(rendered);
            }
            """
        )

    def test_restore_markdown_code_segments_skips_absent_tokens_in_large_html(self):
        self.run_js(
            r"""
            const huge = 'x'.repeat(500001);
            const restored = restoreMarkdownCodeSegments(huge, [
              { token: 'MARKDOWNCODEPLACEHOLDER0TOKEN', segment: '`code`' },
            ]);
            if (restored !== huge) {
              throw new Error(`unexpected rewrite length=${restored.length}`);
            }
            """
        )

    def test_apply_layout_state_marks_narrow_and_wide_reader_widths(self):
        self.run_js(
            r"""
            var childChatLayers = [];
            var layoutState = { pages: 1.15, notes: 0.85, chat: 0.55 };
            var chatCollapsed = false;
            const classes = new Set();
            var document = {
              body: {
                classList: {
                  toggle(name, enabled) {
                    if (enabled) classes.add(name);
                    else classes.delete(name);
                  },
                },
              },
            };
            var readerGrid = {
              style: { gridTemplateColumns: '' },
              getBoundingClientRect() { return { width: 1040 }; },
            };
            var canvasChat = { classList: { toggle() {} } };
            var toggleCanvasButton = null;
            var childChatStack = { style: { setProperty() {} } };

            applyLayoutState();
            if (!classes.has('reader-layout-narrow') || classes.has('reader-layout-wide')) {
              throw new Error(JSON.stringify([...classes]));
            }

            readerGrid.getBoundingClientRect = () => ({ width: 1600 });
            applyLayoutState();
            if (classes.has('reader-layout-narrow') || !classes.has('reader-layout-wide')) {
              throw new Error(JSON.stringify([...classes]));
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

    def test_render_markdown_repairs_repeated_and_unclosed_math_delimiters(self):
        self.run_js(
            r"""
            global.window = {};

            const rendered = renderMarkdown('Repeated $$$$\\int_0^1 x dx$$$$ and open $$\\Omega _ { p } = 2\\pi f _ { p }');
            if (!rendered.includes('\\[\\int_0^1 x dx\\]')) {
              throw new Error(rendered);
            }
            if (!rendered.includes('\\[\\Omega _ { p } = 2\\pi f _ { p }\\]')) {
              throw new Error(rendered);
            }
            if (rendered.includes('$$$$') || rendered.includes('MATHJAXPLACEHOLDER')) {
              throw new Error(rendered);
            }
            """
        )

    def test_render_markdown_repairs_split_left_right_math_delimiters(self):
        self.run_js(
            r"""
            global.window = {};

            const rendered = renderMarkdown('Stored formula ==$\\left$| z $\\right$| < 1== after.');
            if (!rendered.includes('\\(\\left| z \\right|\\)')) {
              throw new Error(rendered);
            }
            if (rendered.includes('$\\left$') || rendered.includes('$\\right$')) {
              throw new Error(rendered);
            }
            if (rendered.includes('MATHJAXPLACEHOLDER')) {
              throw new Error(rendered);
            }
            """
        )

    def test_note_display_markdown_prefers_explanation_over_slide_text(self):
        self.run_js(
            r"""
            const source = noteDisplayMarkdown({
              explanation: 'AI explanation',
              hasExplanation: true,
              slideText: 'Extracted ' + 'prefix '.repeat(40) + '$$\\Omega _ { p } = 2\\pi f _ { p }$$',
            });
            if (!source.includes('AI explanation')) {
              throw new Error(source);
            }
            if (source.includes('PPT/PDF')) {
              throw new Error(source);
            }
            if (source.includes('$$\\Omega _ { p } = 2\\pi f _ { p }$$')) {
              throw new Error(source);
            }
            """
        )

    def test_note_display_markdown_uses_slide_text_without_explanation(self):
        self.run_js(
            r"""
            const source = noteDisplayMarkdown({
              explanation: '本页还没有 AI 讲解。',
              hasExplanation: false,
              slideText: 'Extracted ' + 'prefix '.repeat(40) + '$$\\Omega _ { p } = 2\\pi f _ { p }$$',
            });
            if (source.includes('本页还没有 AI 讲解。')) {
              throw new Error(source);
            }
            if (!source.includes('PPT/PDF')) {
              throw new Error(source);
            }
            if (!source.includes('$$\\Omega _ { p } = 2\\pi f _ { p }$$')) {
              throw new Error(source);
            }
            if (source.includes('...')) {
              throw new Error(source);
            }
            """
        )

    def test_pending_explanation_override_marks_page_as_explained(self):
        self.run_js(
            r"""
            const pendingExplanationSaves = new Map();
            pendingExplanationSaves.set(3, {
              explanation: 'AI explanation',
              startedAt: Date.now(),
            });
            const PENDING_SAVE_TTL_MS = 10000;

            const result = applyPendingExplanationOverrides([{
              slideNumber: 3,
              explanation: '本页还没有 AI 讲解。',
              hasExplanation: false,
              slideText: 'Extracted OCR text',
            }]);

            if (result[0].hasExplanation !== true) {
              throw new Error(JSON.stringify(result[0]));
            }
            const source = noteDisplayMarkdown(result[0]);
            if (source !== 'AI explanation') {
              throw new Error(source);
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

    def test_render_chat_question_shows_question_and_quote_text(self):
        self.run_js(
            r"""
            const rendered = renderChatQuestion({
              question: '\u4e3a\u4ec0\u4e48\u8fd9\u91cc\u5f3a\u8c03\u5468\u671f\u4fe1\u53f7\uff1f',
              quoteText: '\u5468\u671f\u4fe1\u53f7',
            });
            if (!rendered.includes('\u4e3a\u4ec0\u4e48\u8fd9\u91cc\u5f3a\u8c03\u5468\u671f\u4fe1\u53f7\uff1f')) {
              throw new Error(rendered);
            }
            if (!rendered.includes('\u5f15\u7528\u5185\u5bb9') || !rendered.includes('\u5468\u671f\u4fe1\u53f7')) {
              throw new Error(rendered);
            }
            """
        )

    def test_render_chat_turn_marks_child_answer_as_selectable_markdown_source(self):
        self.run_js(
            r"""
            var currentSlideNumber = 2;
            global.window = {
              marked: { parse: value => String(value) },
              DOMPurify: { sanitize: value => String(value) },
            };

            const rendered = renderChatTurn({
              id: 12,
              parentQuestionId: 8,
              depth: 1,
              question: '\u5b50\u63d2\u95ee',
              answer: '\u56de\u7b54 ==\u91cd\u70b9==',
              model: '\u6a21\u578b',
              createdAt: 'today',
            });
            if (!rendered.includes('child-question') || !rendered.includes('data-question-id="12"')) {
              throw new Error(rendered);
            }
            if (!rendered.includes('chat-answer-body') || !rendered.includes('data-slide-number="2"')) {
              throw new Error(rendered);
            }
            if (!rendered.includes('reader-highlight')) {
              throw new Error(rendered);
            }
            """
        )

    def test_child_layers_reserve_width_and_restore_when_closed(self):
        self.run_js(
            r"""
            var childChatLayers = [];
            var layoutState = { pages: 1.15, notes: 0.85, chat: 0.55 };
            var chatCollapsed = false;
            var readerGrid = {
              style: { gridTemplateColumns: '' },
              getBoundingClientRect: () => ({ width: 1600 }),
            };
            var canvasChat = { classList: { toggle() {} } };
            var toggleCanvasButton = { textContent: '' };
            var childChatStack = { style: { setProperty() {} } };

            applyLayoutState();
            const baseColumns = readerGrid.style.gridTemplateColumns;
            if (baseColumns.includes('740px')) {
              throw new Error(baseColumns);
            }

            childChatLayers = [{ layerId: 'a' }, { layerId: 'b' }];
            applyLayoutState();
            const expandedColumns = readerGrid.style.gridTemplateColumns;
            if (!expandedColumns.includes('740px')) {
              throw new Error(expandedColumns);
            }

            childChatLayers = [];
            applyLayoutState();
            if (readerGrid.style.gridTemplateColumns !== baseColumns) {
              throw new Error(readerGrid.style.gridTemplateColumns);
            }
            """
        )

    def test_canvas_chat_defaults_to_collapsed_without_saved_layout_choice(self):
        self.run_js(
            r"""
            var childChatLayers = [];
            var layoutState = { pages: 1.15, notes: 0.85, chat: 0.55 };
            var chatCollapsed = false;
            var readerGrid = {
              style: { gridTemplateColumns: '' },
              getBoundingClientRect: () => ({ width: 1200 }),
            };
            var canvasCollapsed = null;
            var canvasChat = { classList: { toggle(name, value) { canvasCollapsed = value; } } };
            var toggleCanvasButton = { textContent: '' };
            var childChatStack = { style: { setProperty() {} } };
            var localStorage = {
              getItem(key) {
                return String(key).includes('chatCollapsed') ? null : '{}';
              },
            };

            loadLayoutState();
            if (chatCollapsed !== true || canvasCollapsed !== true) {
              throw new Error(JSON.stringify({ chatCollapsed, canvasCollapsed }));
            }
            if (toggleCanvasButton.textContent !== '展开') {
              throw new Error(toggleCanvasButton.textContent);
            }
            """
        )

    def test_canvas_chat_saved_expanded_choice_overrides_collapsed_default(self):
        self.run_js(
            r"""
            var childChatLayers = [];
            var layoutState = { pages: 1.15, notes: 0.85, chat: 0.55 };
            var chatCollapsed = true;
            var readerGrid = {
              style: { gridTemplateColumns: '' },
              getBoundingClientRect: () => ({ width: 1200 }),
            };
            var canvasCollapsed = null;
            var canvasChat = { classList: { toggle(name, value) { canvasCollapsed = value; } } };
            var toggleCanvasButton = { textContent: '' };
            var childChatStack = { style: { setProperty() {} } };
            var localStorage = {
              getItem(key) {
                return String(key).includes('chatCollapsed') ? 'false' : '{}';
              },
            };

            loadLayoutState();
            if (chatCollapsed !== false || canvasCollapsed !== false) {
              throw new Error(JSON.stringify({ chatCollapsed, canvasCollapsed }));
            }
            if (toggleCanvasButton.textContent !== '收起') {
              throw new Error(toggleCanvasButton.textContent);
            }
            """
        )

    def test_child_layer_reserved_width_is_capped_to_keep_main_reader_usable(self):
        self.run_js(
            r"""
            var childChatLayers = [{}, {}, {}, {}, {}];
            var layoutState = { pages: 1.15, notes: 0.85, chat: 0.55 };
            var chatCollapsed = false;
            var readerGrid = {
              style: { gridTemplateColumns: '' },
              getBoundingClientRect: () => ({ width: 1200 }),
            };
            var canvasChat = { classList: { toggle() {} } };
            var toggleCanvasButton = { textContent: '' };
            const stackVars = {};
            var childChatStack = { style: { setProperty(name, value) { stackVars[name] = value; } } };

            applyLayoutState();
            if (!readerGrid.style.gridTemplateColumns.includes('440px')) {
              throw new Error(readerGrid.style.gridTemplateColumns);
            }
            if (stackVars['--child-stack-width'] !== '440px') {
              throw new Error(JSON.stringify(stackVars));
            }
            """
        )

    def test_child_chat_stack_stays_above_fullscreen_frame(self):
        source = READER_HTML.read_text(encoding="utf-8")

        def max_z_index(selector):
            escaped = re.escape(selector)
            values = []
            for block in re.findall(rf"{escaped}\s*\{{(.*?)\}}", source, flags=re.S):
                values.extend(int(value) for value in re.findall(r"z-index\s*:\s*(\d+)", block))
            return max(values) if values else None

        frame_z = max_z_index("body.reader-fullscreen .frame")
        stack_z = max_z_index("body.reader-fullscreen .child-chat-stack")

        self.assertIsNotNone(frame_z)
        self.assertIsNotNone(stack_z)
        self.assertGreater(stack_z, frame_z)

    def test_reader_grid_transition_is_disabled_while_resizing(self):
        source = READER_HTML.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"body\.reader-resizing\s+\.grid\s*\{[^}]*transition\s*:\s*none",
        )

    def test_scroll_panel_anchor_restores_same_visible_element_after_reflow(self):
        self.run_js(
            r"""
            let anchorTop = 60;
            const anchor = {
              isConnected: true,
              getBoundingClientRect() {
                return { top: anchorTop, bottom: anchorTop + 24 };
              },
            };
            const panel = {
              scrollTop: 100,
              scrollHeight: 900,
              clientHeight: 300,
              getBoundingClientRect() {
                return { top: 10, bottom: 310 };
              },
              querySelectorAll(selector) {
                return selector === '.reader-source-fragment' ? [anchor] : [];
              },
            };

            const snapshot = captureScrollPanelAnchor(panel, ['.reader-source-fragment']);
            if (!snapshot || snapshot.offsetTop !== 50) {
              throw new Error(JSON.stringify(snapshot));
            }

            anchorTop = 142;
            restoreScrollPanelAnchor(snapshot);
            if (panel.scrollTop !== 182) {
              throw new Error(String(panel.scrollTop));
            }
            """
        )

    def test_scroll_panel_anchor_prefers_text_range_for_long_reflowed_blocks(self):
        self.run_js(
            r"""
            let rangeTop = 95;
            const range = {
              startContainer: { isConnected: true },
              getClientRects() {
                return [{ top: rangeTop, bottom: rangeTop + 18, width: 1, height: 18 }];
              },
              getBoundingClientRect() {
                return { top: rangeTop, bottom: rangeTop + 18, width: 1, height: 18 };
              },
            };
            const block = {
              isConnected: true,
              getBoundingClientRect() {
                return { top: 20, bottom: 220 };
              },
            };
            const panel = {
              scrollTop: 300,
              scrollHeight: 1200,
              clientHeight: 400,
              getBoundingClientRect() {
                return { top: 40, bottom: 440 };
              },
            };
            const snapshot = {
              panel,
              anchor: block,
              offsetTop: -20,
              range,
              rangeOffsetTop: 55,
              scrollTop: 300,
              scrollLeft: 0,
            };

            rangeTop = 170;
            restoreScrollPanelAnchor(snapshot);
            if (panel.scrollTop !== 375) {
              throw new Error(String(panel.scrollTop));
            }
            """
        )

    def test_scroll_panel_anchor_prefers_visible_text_over_note_container(self):
        self.run_js(
            r"""
            const note = {
              classList: { contains(name) { return name === 'note'; } },
              getBoundingClientRect() {
                return { top: 40, bottom: 800 };
              },
            };
            const paragraph = {
              classList: { contains() { return false; } },
              getBoundingClientRect() {
                return { top: 120, bottom: 168 };
              },
            };
            const panel = {
              scrollTop: 300,
              scrollHeight: 1200,
              clientHeight: 420,
              getBoundingClientRect() {
                return { top: 40, bottom: 460 };
              },
              querySelectorAll(selector) {
                if (selector === '.note.active .note-body p') return [paragraph];
                if (selector === '.note.active' || selector === '.note') return [note];
                return [];
              },
            };

            const snapshot = captureScrollPanelAnchor(panel, [
              '.note.active .note-body p',
              '.note.active',
              '.note',
            ]);
            if (!snapshot || snapshot.anchor !== paragraph) {
              throw new Error(JSON.stringify({
                anchorWasParagraph: snapshot?.anchor === paragraph,
                offsetTop: snapshot?.offsetTop,
              }));
            }
            """
        )

    def test_scroll_panel_anchor_reselects_semantic_anchor_after_dom_rebuild(self):
        self.run_js(
            r"""
            const oldTurn = {
              isConnected: false,
              dataset: { questionId: '9' },
              matches(selector) {
                return selector === '[data-question-id]';
              },
              getBoundingClientRect() {
                return { top: 60, bottom: 100 };
              },
            };
            const newTurn = {
              isConnected: true,
              getBoundingClientRect() {
                return { top: 150, bottom: 190 };
              },
            };
            const panel = {
              scrollTop: 40,
              scrollHeight: 600,
              clientHeight: 240,
              scrollLeft: 0,
              getBoundingClientRect() {
                return { top: 30, bottom: 270 };
              },
              querySelector(selector) {
                if (selector === '[data-question-id="9"]') return newTurn;
                return null;
              },
            };
            const snapshot = {
              panel,
              anchor: oldTurn,
              anchorSelector: stableScrollAnchorSelector(oldTurn),
              offsetTop: 30,
              scrollTop: 40,
              scrollLeft: 0,
            };

            restoreScrollPanelAnchor(snapshot);
            if (panel.scrollTop !== 130) {
              throw new Error(String(panel.scrollTop));
            }
            """
        )

    def test_layout_anchor_restore_is_throttled_to_latest_animation_frame(self):
        self.run_js(
            r"""
            const restored = [];
            let nextId = 1;
            const frames = new Map();
            global.window = {
              requestAnimationFrame(callback) {
                const id = nextId++;
                frames.set(id, callback);
                return id;
              },
              cancelAnimationFrame(id) {
                frames.delete(id);
              },
            };
            restoreReaderViewportAnchors = snapshot => restored.push(snapshot.marker);

            restoreReaderAnchorsAfterLayoutChange({ marker: 'first' }, { immediate: false });
            restoreReaderAnchorsAfterLayoutChange({ marker: 'second' }, { immediate: false });
            if (frames.size !== 1) {
              throw new Error(`frames=${frames.size}`);
            }
            Array.from(frames.values()).forEach(callback => callback());
            if (restored.join(',') !== 'second') {
              throw new Error(restored.join(','));
            }
            """
        )

    def test_resize_preserves_reader_viewport_anchors_during_layout_changes(self):
        self.run_js(
            r"""
            const restored = [];
            var layoutState = { pages: 1.15, notes: 0.85, chat: 0.55 };
            var chatCollapsed = false;
            var childChatLayers = [];
            var readerGrid = {
              style: { gridTemplateColumns: '' },
              getBoundingClientRect: () => ({ width: 1000 }),
            };
            var canvasChat = { classList: { toggle() {} } };
            var toggleCanvasButton = { textContent: '' };
            var childChatStack = { style: { setProperty() {} } };
            var activeResize = {
              handle: { classList: { remove() {} } },
              kind: 'pages-notes',
              startX: 200,
              start: { ...layoutState },
              anchors: { marker: 'before-resize' },
            };
            var suppressObserverUntil = 0;
            var VIEWPORT_ANCHOR_MS = 1400;
            restoreReaderAnchorsAfterLayoutChange = snapshot => restored.push(snapshot);

            updateResize({
              preventDefault() {},
              clientX: 260,
            });

            if (restored.length !== 1 || restored[0].marker !== 'before-resize') {
              throw new Error(JSON.stringify(restored));
            }
            if (suppressObserverUntil <= 0) {
              throw new Error(String(suppressObserverUntil));
            }
            """
        )

    def test_canvas_chat_open_and_toggle_preserve_reader_viewport_anchors(self):
        self.run_js(
            r"""
            const restored = [];
            let captureCount = 0;
            var childChatLayers = [];
            var layoutState = { pages: 1.15, notes: 0.85, chat: 0.55 };
            var chatCollapsed = true;
            var suppressObserverUntil = 0;
            var VIEWPORT_ANCHOR_MS = 1400;
            var readerGrid = {
              style: { gridTemplateColumns: '' },
              getBoundingClientRect: () => ({ width: 1200 }),
            };
            var canvasChat = { classList: { toggle() {} } };
            var toggleCanvasButton = { textContent: '' };
            var childChatStack = { style: { setProperty() {} } };
            var saveCount = 0;
            var saveLayoutState = () => { saveCount += 1; };
            captureReaderViewportAnchors = () => ({ marker: `anchor-${++captureCount}` });
            restoreReaderAnchorsAfterLayoutChange = (snapshot, options) => {
              restored.push({ snapshot, options });
            };

            openCanvasChat(false);
            toggleCanvasChat();

            if (chatCollapsed !== true) {
              throw new Error(`chatCollapsed=${chatCollapsed}`);
            }
            if (saveCount !== 2) {
              throw new Error(`saveCount=${saveCount}`);
            }
            if (restored.length !== 2) {
              throw new Error(JSON.stringify(restored));
            }
            if (restored[0].snapshot.marker !== 'anchor-1' || restored[1].snapshot.marker !== 'anchor-2') {
              throw new Error(JSON.stringify(restored));
            }
            if (restored.some(item => item.options?.immediate !== false)) {
              throw new Error(JSON.stringify(restored));
            }
            if (suppressObserverUntil <= 0) {
              throw new Error(String(suppressObserverUntil));
            }
            """
        )

    def test_child_chat_open_and_close_preserve_reader_viewport_anchors(self):
        self.run_js(
            r"""
            const restored = [];
            const emitted = [];
            let captureCount = 0;
            var Streamlit = { setComponentValue: value => emitted.push(value) };
            var deckId = 3;
            var currentSlideNumber = 2;
            var suppressObserverUntil = 0;
            var VIEWPORT_ANCHOR_MS = 1400;
            var childPanelScrollToBottomLayerId = null;
            var childChatLayers = [];
            var selectionHint = { textContent: '' };
            var pageRoot = { scrollTop: 7 };
            var canvasMessages = { scrollTop: 9 };
            var renderCount = 0;
            var layoutCount = 0;
            noteAnchorForSlide = () => null;
            questionById = questionId => ({ id: questionId, depth: 0, question: 'parent' });
            childLayerScrollPositions = () => new Map();
            renderChildQuestionStack = () => { renderCount += 1; };
            applyLayoutState = () => { layoutCount += 1; };
            restoreReaderScrollPositions = () => {
              throw new Error('legacy absolute scroll restore should not be used for layout toggles');
            };
            captureReaderViewportAnchors = () => ({ marker: `child-anchor-${++captureCount}` });
            restoreReaderAnchorsAfterLayoutChange = (snapshot, options) => {
              restored.push({ snapshot, options });
            };

            const opened = openChildChatFromQuote({
              sourceKind: 'question_answer',
              questionId: 10,
              depth: 0,
              selectedText: 'answer',
            });

            if (!opened || childChatLayers.length !== 1) {
              throw new Error(JSON.stringify(childChatLayers));
            }
            const layerId = childChatLayers[0].layerId;
            closeChildLayer(layerId);

            if (childChatLayers.length !== 0) {
              throw new Error(JSON.stringify(childChatLayers));
            }
            if (renderCount !== 2 || layoutCount !== 2) {
              throw new Error(JSON.stringify({ renderCount, layoutCount }));
            }
            if (restored.length !== 2) {
              throw new Error(JSON.stringify(restored));
            }
            if (restored[0].snapshot.marker !== 'child-anchor-1' || restored[1].snapshot.marker !== 'child-anchor-2') {
              throw new Error(JSON.stringify(restored));
            }
            if (restored.some(item => item.options?.immediate !== false)) {
              throw new Error(JSON.stringify(restored));
            }
            if (suppressObserverUntil <= 0) {
              throw new Error(String(suppressObserverUntil));
            }
            if (emitted.length !== 1 || emitted[0].action !== 'close_slide_question' || emitted[0].questionId !== 10) {
              throw new Error(JSON.stringify(emitted));
            }
            """
        )

    def test_child_chat_messages_are_independent_scroll_panels(self):
        self.run_js(
            r"""
            const childPanel = { marker: 'child' };
            const pagePanel = { marker: 'page' };
            var pageRoot = pagePanel;
            const target = {
              closest(selector) {
                if (selector === '.canvas-input') return null;
                if (selector === '.page-jump-input') return null;
                if (selector === '.note-editor') return null;
                if (selector.includes('.child-chat-messages')) return childPanel;
                return null;
              },
            };

            const result = nearestScrollPanel(target);
            if (result !== childPanel) {
              throw new Error(JSON.stringify(result));
            }
            """
        )

    def test_child_chat_stack_preserves_existing_panel_scroll(self):
        self.run_js(
            r"""
            const oldPanel = {
              dataset: { childMessages: 'layer-a' },
              scrollTop: 42,
              scrollHeight: 200,
            };
            const newPanel = {
              dataset: { childMessages: 'layer-a' },
              scrollTop: 0,
              scrollHeight: 200,
            };
            var childChatLayers = [{ layerId: 'layer-a', parentQuestionId: 1 }];
            var childPanelScrollToBottomLayerId = null;
            var childChatStack = {
              _rendered: false,
              set innerHTML(value) {
                this._rendered = true;
                this._html = value;
              },
              get innerHTML() {
                return this._html || '';
              },
              querySelectorAll(selector) {
                if (selector !== '.child-chat-messages') return [];
                return this._rendered ? [newPanel] : [oldPanel];
              },
            };
            questionById = () => ({ question: '\u6839\u95ee\u9898' });
            childQuestionsFor = () => [{ id: 2, parentQuestionId: 1, question: '\u5b50\u95ee', answer: '\u7b54' }];
            renderChatTurn = () => '<div class="chat-turn">child</div>';
            typesetTargets = () => Promise.resolve(false);
            applyChatSourceMaps = () => {};

            renderChildQuestionStack();
            if (newPanel.scrollTop !== 42) {
              throw new Error(String(newPanel.scrollTop));
            }
            """
        )

    def test_child_chat_stack_scrolls_new_answer_to_question_top(self):
        self.run_js(
            r"""
            const newQuestionTurn = { offsetTop: 180 };
            const newPanel = {
              dataset: { childMessages: 'layer-a' },
              scrollTop: 0,
              scrollHeight: 800,
              offsetTop: 20,
              querySelector(selector) {
                if (selector === '[data-question-id="3"]') return newQuestionTurn;
                return null;
              },
            };
            var childChatLayers = [{ layerId: 'layer-a', parentQuestionId: 1 }];
            var childPanelScrollToBottomLayerId = 'layer-a';
            var childChatStack = {
              set innerHTML(value) {
                this._html = value;
              },
              get innerHTML() {
                return this._html || '';
              },
              querySelectorAll(selector) {
                return selector === '.child-chat-messages' ? [newPanel] : [];
              },
            };
            questionById = () => ({ question: '\u6839\u95ee\u9898' });
            childQuestionsFor = () => [
              { id: 2, parentQuestionId: 1, question: '\u65e7\u5b50\u95ee', answer: '\u65e7\u7b54' },
              { id: 3, parentQuestionId: 1, question: '\u65b0\u5b50\u95ee', answer: '\u65b0\u7b54' },
            ];
            renderChatTurn = item => `<div class="chat-turn" data-question-id="${item.id}">child</div>`;
            typesetTargets = () => Promise.resolve(false);
            applyChatSourceMaps = () => {};

            renderChildQuestionStack();
            if (newPanel.scrollTop !== 160) {
              throw new Error(String(newPanel.scrollTop));
            }
            if (childPanelScrollToBottomLayerId !== null) {
              throw new Error(String(childPanelScrollToBottomLayerId));
            }
            """
        )

    def test_chat_question_top_scroll_helper_targets_question_start(self):
        self.run_js(
            r"""
            const newQuestionTurn = { offsetTop: 220 };
            const panel = {
              scrollTop: 10,
              scrollHeight: 1200,
              clientHeight: 360,
              offsetTop: 20,
              querySelector(selector) {
                if (selector === '[data-question-id="20"]') return newQuestionTurn;
                return null;
              },
            };

            if (typeof scrollChatQuestionToTop !== 'function') {
              throw new Error('missing scrollChatQuestionToTop');
            }
            const focused = scrollChatQuestionToTop(panel, 20);
            if (!focused || panel.scrollTop !== 200) {
              throw new Error(JSON.stringify({ focused, scrollTop: panel.scrollTop }));
            }
            """
        )

    def test_canvas_chat_render_can_focus_latest_question_after_submit(self):
        source = READER_HTML.read_text(encoding="utf-8")

        self.assertIn("focusLatestQuestion", source)
        self.assertIn("scrollChatQuestionToTop(canvasMessages", source)
        self.assertRegex(
            source,
            r"renderChatForPage\(currentSlideNumber,\s*\{[^}]*focusLatestQuestion",
        )

    def test_chat_bottom_button_only_shows_when_scrolled_above_bottom(self):
        self.run_js(
            r"""
            const classes = {};
            const button = {
              hidden: false,
              classList: {
                toggle(name, value) { classes[name] = value; },
              },
            };
            const panel = {
              scrollTop: 720,
              clientHeight: 260,
              scrollHeight: 1000,
            };

            updateChatBottomButton(panel, button);
            if (button.hidden !== true || classes.hidden !== true) {
              throw new Error(JSON.stringify({ hidden: button.hidden, classes }));
            }

            panel.scrollTop = 200;
            updateChatBottomButton(panel, button);
            if (button.hidden !== false || classes.hidden !== false) {
              throw new Error(JSON.stringify({ hidden: button.hidden, classes }));
            }
            """
        )

    def test_scroll_bottom_buttons_are_not_header_actions(self):
        source = READER_HTML.read_text(encoding="utf-8")
        canvas_header = re.search(
            r'<header class="canvas-chat-header">.*?</header>',
            source,
            re.S,
        ).group(0)

        self.assertNotIn("canvasScrollBottomButton", canvas_header)
        self.assertRegex(
            source,
            r'<button[^>]+class="[^"]*chat-scroll-bottom[^"]*canvas-scroll-bottom',
        )
        self.assertRegex(
            source,
            r'<button[^>]+class="[^"]*chat-scroll-bottom[^"]*child-chat-bottom',
        )

    def test_closing_child_layer_marks_closed_anchor_without_reparenting(self):
        self.run_js(
            r"""
            const emitted = [];
            var Streamlit = { setComponentValue: value => emitted.push(value) };
            var deckId = 3;
            var currentSlideNumber = 2;
            var suppressObserverUntil = 0;
            var VIEWPORT_ANCHOR_MS = 1400;
            var childChatLayers = [
              { layerId: 'l1', parentQuestionId: 10, depth: 1 },
              { layerId: 'l2', parentQuestionId: 20, depth: 2 },
            ];
            var noteAnchorForSlide = () => null;
            var pageRoot = { scrollTop: 7 };
            var canvasMessages = { scrollTop: 9 };
            childLayerScrollPositions = () => new Map();
            renderChildQuestionStack = () => {};
            applyLayoutState = () => {};
            restoreReaderScrollPositions = () => {};
            captureReaderViewportAnchors = () => ({ marker: 'before-close' });
            restoreReaderAnchorsAfterLayoutChange = () => {};

            closeChildLayer('l1');
            if (childChatLayers.length !== 0) {
              throw new Error(JSON.stringify(childChatLayers));
            }
            if (emitted.length !== 1 || emitted[0].action !== 'close_slide_question' || emitted[0].questionId !== 10) {
              throw new Error(JSON.stringify(emitted));
            }
            """
        )

    def test_slide_change_clears_open_child_stack_without_persisting_status_change(self):
        self.run_js(
            r"""
            const emitted = [];
            var Streamlit = { setComponentValue: value => emitted.push(value) };
            var deckId = 3;
            var currentSlideNumber = 2;
            var suppressObserverUntil = 0;
            var VIEWPORT_ANCHOR_MS = 1400;
            var childChatLayers = [
              { layerId: 'l1', parentQuestionId: 10, depth: 1 },
              { layerId: 'l2', parentQuestionId: 20, depth: 2 },
            ];
            renderChildQuestionStack = () => {};
            applyLayoutState = () => {};

            closeChildLayersForSlideChange();
            if (childChatLayers.length !== 0) {
              throw new Error(JSON.stringify(childChatLayers));
            }
            if (emitted.length !== 0) {
              throw new Error(JSON.stringify(emitted));
            }
            """
        )

    def test_bookmark_title_falls_back_to_slide_title(self):
        self.run_js(
            r"""
            const title = bookmarkTitleForPage({
              slideNumber: 2,
              title: 'Signals',
              bookmarkTitle: '',
            });
            if (title !== 'Signals') {
              throw new Error(title);
            }
            """
        )

    def test_render_bookmark_list_shows_editable_bookmarks(self):
        self.run_js(
            r"""
            var pages = [
              { slideNumber: 2, title: 'Signals', bookmarkEnabled: true, bookmarkTitle: '' },
              { slideNumber: 3, title: 'Noise', bookmarkEnabled: false, bookmarkTitle: '' },
            ];
            const html = renderBookmarkList();
            if (!html.includes('data-bookmark-row="2"') || !html.includes('data-bookmark-title="2"')) {
              throw new Error(html);
            }
            if (!html.includes('Signals') || html.includes('Noise')) {
              throw new Error(html);
            }
            """
        )

    def test_toggle_page_bookmark_updates_local_page_and_emits_action(self):
        self.run_js(
            r"""
            const emitted = [];
            var pages = [
              { slideNumber: 2, title: 'Signals', bookmarkEnabled: false, bookmarkTitle: '' },
            ];
            var deckId = 7;
            var Streamlit = { setComponentValue: value => emitted.push(value) };
            var document = { querySelector() { return null; } };
            var bookmarkMenuButton = null;
            var bookmarkPopover = null;

            togglePageBookmark(2);
            if (!pages[0].bookmarkEnabled) {
              throw new Error(JSON.stringify(pages[0]));
            }
            if (emitted.length !== 1 || emitted[0].action !== 'toggle_slide_bookmark' || emitted[0].enabled !== true) {
              throw new Error(JSON.stringify(emitted));
            }
            if ('title' in emitted[0]) {
              throw new Error(JSON.stringify(emitted[0]));
            }
            """
        )

    def test_rename_bookmark_saves_custom_title_and_keeps_enabled(self):
        self.run_js(
            r"""
            const emitted = [];
            var pages = [
              { slideNumber: 2, title: 'Signals', bookmarkEnabled: false, bookmarkTitle: '' },
            ];
            var deckId = 7;
            var Streamlit = { setComponentValue: value => emitted.push(value) };
            var document = { querySelector() { return null; } };
            var bookmarkMenuButton = null;
            var bookmarkPopover = null;

            renameBookmark(2, '  Chapter start  ');
            if (!pages[0].bookmarkEnabled || pages[0].bookmarkTitle !== 'Chapter start') {
              throw new Error(JSON.stringify(pages[0]));
            }
            if (emitted.length !== 1 || emitted[0].action !== 'rename_slide_bookmark' || emitted[0].title !== 'Chapter start') {
              throw new Error(JSON.stringify(emitted));
            }
            """
        )


if __name__ == "__main__":
    unittest.main()
