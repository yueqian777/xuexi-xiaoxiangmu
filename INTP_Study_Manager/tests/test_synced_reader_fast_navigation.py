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


class SyncedReaderFastNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = _node_executable()
        if not cls.node:
            raise unittest.SkipTest("Node.js is not available for synced-reader JS tests")
        cls.source = READER_HTML.read_text(encoding="utf-8")
        helper_names = [
            "escapeHtml",
            "storageKey",
            "connectedTypesetTargets",
            "scheduleMathJaxRetry",
            "flushTypesetQueue",
            "typesetTargets",
            "pageForSlide",
            "pageIndexForSlide",
            "pageIndexDistance",
            "readScrollState",
            "buildReaderStructureSignature",
            "pageImageCacheKey",
            "touchPageImageCache",
            "enforcePageImageCacheLimit",
            "prioritizeImageCacheAroundSlide",
            "pruneExpiredImageRequests",
            "cachedImageForPage",
            "applyCachedPageImages",
            "shouldRecenterAfterActiveImagePatch",
            "centerPageAfterImageSettles",
            "shouldRenderPageImage",
            "pageVisualRenderKey",
            "renderPageVisual",
            "syncActivePageDom",
            "updateRenderedPageImageWindow",
            "desiredImageWindowSlideNumbers",
            "missingImageWindowSlides",
            "requestImageWindowIfNeeded",
        ]
        cls.js_helpers = "\n\n".join(
            block for name in helper_names if (block := _extract_function(cls.source, name))
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

    def test_mathjax_unavailable_retry_is_coalesced(self):
        self.run_js(
            r"""
            let pendingTypesetTargets = new Set();
            let typesetFlushTimer = null;
            let mathJaxRetryTimer = null;
            let typesetChain = Promise.resolve();
            const TYPESET_BATCH_DELAY_MS = 40;
            const MATHJAX_RETRY_MS = 180;
            let scheduled = 0;
            global.window = {
              MathJax: null,
              setTimeout: () => {
                scheduled += 1;
                return scheduled;
              },
              clearTimeout: () => {},
            };

            typesetTargets([{ isConnected: true }]);
            typesetTargets([{ isConnected: true }]);
            typesetTargets([{ isConnected: true }]);
            if (scheduled !== 1) {
              throw new Error(`expected one retry timer, got ${scheduled}`);
            }
            """
        )

    def test_disconnected_nodes_are_not_sent_to_mathjax(self):
        self.run_js(
            r"""
            let pendingTypesetTargets = new Set();
            let typesetFlushTimer = null;
            let mathJaxRetryTimer = null;
            let typesetChain = Promise.resolve();
            const TYPESET_BATCH_DELAY_MS = 0;
            const MATHJAX_RETRY_MS = 180;
            const connected = { isConnected: true };
            const detached = { isConnected: false };
            let seenTargets = [];
            global.window = {
              setTimeout: (fn) => {
                fn();
                return 1;
              },
              clearTimeout: () => {},
              MathJax: {
                typesetClear: () => {},
                typesetPromise: (targets) => {
                  seenTargets = targets;
                  return Promise.resolve();
                },
              },
            };
            global.document = {
              contains: (target) => target !== detached,
            };

            typesetTargets([connected, detached]);
            typesetChain.then(() => {
              if (seenTargets.length !== 1 || seenTargets[0] !== connected) {
                throw new Error(`unexpected targets: ${seenTargets.length}`);
              }
            });
            """
        )

    def test_nearby_content_hydration_is_scheduled_for_fast_navigation(self):
        self.assertIn("function scheduleNearbyContent", self.source)
        self.assertIn("scheduleNearbyContent(currentSlideNumber)", self.source)

    def test_empty_scroll_state_does_not_override_initial_slide(self):
        self.run_js(
            r"""
            let deckId = 9;
            let currentSlideNumber = 1;
            global.localStorage = {
              getItem: () => null,
            };

            const state = readScrollState();
            if (state !== null) {
              throw new Error(JSON.stringify(state));
            }
            """
        )

    def test_patchable_note_metadata_does_not_change_reader_structure_signature(self):
        self.run_js(
            r"""
            const before = buildReaderStructureSignature(9, [
              {
                slideNumber: 1,
                title: '旧标题',
                pageType: '',
                sectionIndex: 0,
                summary: '',
                slideRole: '',
                keyPoints: '',
              },
            ], []);
            const after = buildReaderStructureSignature(9, [
              {
                slideNumber: 1,
                title: '新标题',
                pageType: '正文页',
                sectionIndex: 3,
                summary: '新摘要',
                slideRole: '承接',
                keyPoints: '重点',
              },
            ], []);
            if (before !== after) {
              throw new Error(`${before}\n${after}`);
            }
            """
        )

    def test_image_window_request_rechecks_page_state_before_notify(self):
        self.run_js(
            r"""
            let pages = [{ slideNumber: 1, imageAvailable: true, image: '' }];
            let deckId = 9;
            let lastPositionNotifyKey = '';
            let positionNotifyTimer = null;
            let pendingImageWindowRequest = null;
            const pageImageCache = new Map();
            const pendingImageRequests = new Map();
            const IMAGE_PREFETCH_RADIUS = 0;
            const IMAGE_WINDOW_NOTIFY_IDLE_MS = 0;
            const IMAGE_WINDOW_PENDING_TTL_MS = 10000;
            const notifications = [];
            const Streamlit = {
              setComponentValue: value => notifications.push(value),
            };
            function pageForSlide(slideNumber) {
              return pages.find(item => Number(item.slideNumber) === Number(slideNumber)) || null;
            }
            function createComponentToken() {
              return 'token';
            }
            global.window = {
              clearTimeout: () => {},
              setTimeout: fn => {
                pages[0].image = 'data:image/png;base64,loaded';
                fn();
                return 1;
              },
            };

            requestImageWindowIfNeeded(1);
            if (notifications.length !== 0) {
              throw new Error(`expected no stale notification, got ${notifications.length}`);
            }
            """
        )

    def test_received_page_images_are_reused_when_later_payload_omits_them(self):
        self.run_js(
            r"""
            let deckId = 9;
            const pageImageCache = new Map();
            const pendingImageRequests = new Map();

            const first = applyCachedPageImages([
              { slideNumber: 2, imageAvailable: true, image: 'data:image/png;base64,two' },
            ]);
            if (first[0].image !== 'data:image/png;base64,two') {
              throw new Error(JSON.stringify(first));
            }

            const second = applyCachedPageImages([
              { slideNumber: 2, imageAvailable: true, image: '' },
            ]);
            if (second[0].image !== 'data:image/png;base64,two') {
              throw new Error(JSON.stringify(second));
            }
            """
        )

    def test_page_image_cache_prunes_evicted_images_from_render_payload(self):
        self.run_js(
            r"""
            let deckId = 9;
            const pageImageCache = new Map();
            const pendingImageRequests = new Map();
            const PAGE_IMAGE_CACHE_MAX_SLIDES = 2;

            const first = applyCachedPageImages([
              { slideNumber: 1, imageAvailable: true, image: 'data:image/png;base64,one' },
              { slideNumber: 2, imageAvailable: true, image: 'data:image/png;base64,two' },
              { slideNumber: 3, imageAvailable: true, image: 'data:image/png;base64,three' },
            ], 3);

            if (pageImageCache.size !== 2) {
              throw new Error(`expected bounded cache, got ${pageImageCache.size}`);
            }
            if (first[0].image !== '' || first[1].image === '' || first[2].image === '') {
              throw new Error(JSON.stringify(first.map(page => page.image)));
            }

            const second = applyCachedPageImages([
              { slideNumber: 1, imageAvailable: true, image: '' },
              { slideNumber: 2, imageAvailable: true, image: '' },
              { slideNumber: 3, imageAvailable: true, image: '' },
            ], 3);
            if (second[0].image !== '' || second[1].image === '' || second[2].image === '') {
              throw new Error(JSON.stringify(second.map(page => page.image)));
            }
            """
        )

    def test_page_image_cache_preserves_target_window_images(self):
        self.run_js(
            r"""
            let deckId = 9;
            const pageImageCache = new Map();
            const pendingImageRequests = new Map();
            const PAGE_IMAGE_CACHE_MAX_SLIDES = 3;

            const pages = [1, 2, 3, 4, 5].map(slideNumber => ({
              slideNumber,
              imageAvailable: true,
              image: `data:image/png;base64,${slideNumber}`,
            }));

            const first = applyCachedPageImages(pages, 3);
            if (first[1].image === '' || first[2].image === '' || first[3].image === '') {
              throw new Error(JSON.stringify(first.map(page => page.image)));
            }
            if (first[0].image !== '' || first[4].image !== '') {
              throw new Error(JSON.stringify(first.map(page => page.image)));
            }
            if ([...pageImageCache.keys()].join(',') !== '9:2,9:3,9:4') {
              throw new Error([...pageImageCache.keys()].join(','));
            }
            """
        )

    def test_image_window_request_sends_prefetch_window_and_dedupes_pending_slides(self):
        self.run_js(
            r"""
            let pages = Array.from({ length: 9 }, (_, index) => ({
              slideNumber: index + 1,
              imageAvailable: true,
              image: '',
            }));
            let deckId = 9;
            let lastPositionNotifyKey = '';
            let positionNotifyTimer = null;
            let pendingImageWindowRequest = null;
            const pageImageCache = new Map();
            const pendingImageRequests = new Map();
            const IMAGE_PREFETCH_RADIUS = 2;
            const IMAGE_WINDOW_NOTIFY_IDLE_MS = 0;
            const IMAGE_WINDOW_PENDING_TTL_MS = 10000;
            const notifications = [];
            const Streamlit = {
              setComponentValue: value => notifications.push(value),
            };
            function pageForSlide(slideNumber) {
              return pages.find(item => Number(item.slideNumber) === Number(slideNumber)) || null;
            }
            function createComponentToken() {
              return 'token';
            }
            Date.now = () => 1000;
            global.window = {
              clearTimeout: () => {},
              setTimeout: fn => {
                fn();
                return 1;
              },
            };

            requestImageWindowIfNeeded(5);
            requestImageWindowIfNeeded(5);

            if (notifications.length !== 1) {
              throw new Error(`expected one request, got ${notifications.length}`);
            }
            const payload = notifications[0];
            if (payload.imageWindowRadius !== 2) {
              throw new Error(JSON.stringify(payload));
            }
            if (payload.imageWindowSlideNumbers.join(',') !== '3,4,5,6,7') {
              throw new Error(JSON.stringify(payload));
            }
            if (missingImageWindowSlides(5).length !== 0) {
              throw new Error('pending slides were requested again');
            }
            """
        )

    def test_active_image_patch_recenters_same_slide_only(self):
        self.run_js(
            r"""
            if (!shouldRecenterAfterActiveImagePatch([3], 3, true)) {
              throw new Error('active patched image should recenter after load');
            }
            if (shouldRecenterAfterActiveImagePatch([2], 3, true)) {
              throw new Error('other slide image patch should not move reader');
            }
            if (shouldRecenterAfterActiveImagePatch([3], 3, false)) {
              throw new Error('slide change already has explicit centering');
            }
            """
        )

    def test_page_visual_decodes_only_active_render_window(self):
        self.run_js(
            r"""
            const PAGE_IMAGE_RENDER_RADIUS = 2;
            let deckId = 4;
            let pages = Array.from({ length: 9 }, (_, index) => ({
              slideNumber: index + 1,
              imageAvailable: true,
              image: `data:image/png;base64,page${index + 1}`,
            }));

            if (!shouldRenderPageImage(pages[4], 5)) {
              throw new Error('active page image should render');
            }
            if (!shouldRenderPageImage(pages[2], 5) || !shouldRenderPageImage(pages[6], 5)) {
              throw new Error('nearby images should render');
            }
            if (shouldRenderPageImage(pages[1], 5) || shouldRenderPageImage(pages[7], 5)) {
              throw new Error('far images should stay as placeholders');
            }
            if (!renderPageVisual(pages[4], 5).includes('<img')) {
              throw new Error('active image markup missing');
            }
            if (renderPageVisual(pages[1], 5).includes('<img')) {
              throw new Error('far image should not be decoded into the DOM');
            }
            """
        )

    def test_page_placeholder_preserves_image_aspect_ratio(self):
        self.assertIn("aspect-ratio: 4 / 3;", self.source)

    def test_update_rendered_page_image_window_evicts_far_dom_images(self):
        self.run_js(
            r"""
            const PAGE_IMAGE_RENDER_RADIUS = 1;
            let deckId = 4;
            let currentSlideNumber = 3;
            let pages = [1, 2, 3, 4, 5].map(number => ({
              slideNumber: number,
              imageAvailable: true,
              image: `data:image/png;base64,page${number}`,
            }));
            const visuals = new Map();
            for (const page of pages) {
              visuals.set(`page-${page.slideNumber}`, {
                querySelector(selector) {
                  return selector === '.page-visual' ? this.visual : null;
                },
                visual: {
                  dataset: {},
                  innerHTML: '<img src="old" />',
                },
              });
            }
            var document = {
              getElementById(id) {
                return visuals.get(id) || null;
              },
            };

            updateRenderedPageImageWindow(3);

            const decoded = pages
              .filter(page => visuals.get(`page-${page.slideNumber}`).visual.innerHTML.includes('<img'))
              .map(page => page.slideNumber);
            if (JSON.stringify(decoded) !== JSON.stringify([2, 3, 4])) {
              throw new Error(JSON.stringify(decoded));
            }
            if (visuals.get('page-1').visual.innerHTML.includes('<img') || visuals.get('page-5').visual.innerHTML.includes('<img')) {
              throw new Error('far DOM images were not evicted');
            }
            """
        )

    def test_page_visual_render_key_changes_for_same_length_image_content(self):
        self.run_js(
            r"""
            const PAGE_IMAGE_RENDER_RADIUS = 2;
            let deckId = 4;
            let currentSlideNumber = 1;
            let pages = [];
            const first = {
              slideNumber: 1,
              imageAvailable: true,
              image: 'data:image/png;base64,AAAABBBBCCCC',
            };
            const second = {
              slideNumber: 1,
              imageAvailable: true,
              image: 'data:image/png;base64,ZZZZYYYYXXXX',
            };
            pages = [first];
            if (first.image.length !== second.image.length) {
              throw new Error('test data must keep equal length');
            }
            if (pageVisualRenderKey(first, 1) === pageVisualRenderKey(second, 1)) {
              throw new Error('same-length image content must not reuse DOM render key');
            }
            """
        )

    def test_sync_active_page_dom_moves_active_classes_after_patch_target_change(self):
        self.run_js(
            r"""
            const elements = new Map();
            function makeElement(id) {
              const classes = new Set(['active']);
              const element = {
                id,
                classList: {
                  add(value) { classes.add(value); },
                  remove(value) { classes.delete(value); },
                  contains(value) { return classes.has(value); },
                },
              };
              elements.set(id, element);
              return element;
            }
            makeElement('page-1');
            makeElement('note-1');
            makeElement('page-5').classList.remove('active');
            makeElement('note-5').classList.remove('active');
            var document = {
              querySelectorAll(selector) {
                if (selector !== '.page.active,.note.active') return [];
                return Array.from(elements.values()).filter(element => element.classList.contains('active'));
              },
              getElementById(id) {
                return elements.get(id) || null;
              },
            };

            syncActivePageDom(5);

            if (elements.get('page-1').classList.contains('active') || elements.get('note-1').classList.contains('active')) {
              throw new Error('old active classes remained');
            }
            if (!elements.get('page-5').classList.contains('active') || !elements.get('note-5').classList.contains('active')) {
              throw new Error('target active classes missing');
            }
            """
        )

    def test_scroll_page_activation_waits_for_image_settle(self):
        self.assertIn(
            "centerPageAfterImageSettles(currentSlideNumber, options.behavior || 'smooth');",
            self.source,
        )
        self.assertIn("const settledBehavior = readingMode === 'paged' ? 'auto' : behavior;", self.source)
        self.assertIn("viewportAnchorState = null;", self.source)

    def test_patch_refresh_sets_target_before_image_window_update(self):
        self.assertIn(
            "currentSlideNumber = pageForSlide(targetSlide)\n          ? targetSlide\n          : previousCurrentSlide;\n        const { typesetQueue, imageChangedSlides } = patchRenderedReader(previousPages);",
            self.source,
        )
        self.assertIn("syncActivePageDom(currentSlideNumber);", self.source)

    def test_center_page_uses_clamped_center_calculation(self):
        self.assertIn(
            "const targetTop = pageRect.top - rootRect.top + pageRoot.scrollTop;",
            self.source,
        )
        self.assertIn("centeredScrollTopForElement(pageRoot.clientHeight, targetTop", self.source)
        self.assertIn("pageRoot.style.scrollBehavior = 'auto';", self.source)

    def test_resize_handles_have_wide_hit_area_and_hover_cursor(self):
        self.assertIn(
            "grid-template-columns: minmax(260px, 1.15fr) var(--resize-handle-width)",
            self.source,
        )
        self.assertIn("--resize-handle-width: 14px;", self.source)
        self.assertIn(".resize-handle {", self.source)
        self.assertIn("cursor: col-resize;", self.source)
        self.assertIn("data:image/svg+xml", self.source)
        self.assertIn(".resize-handle::before", self.source)
        self.assertIn(".resize-handle:hover::before", self.source)
        self.assertIn("document.body.classList.add('reader-resizing')", self.source)


if __name__ == "__main__":
    unittest.main()
