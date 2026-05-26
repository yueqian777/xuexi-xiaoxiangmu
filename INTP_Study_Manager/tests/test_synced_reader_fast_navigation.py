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


class SyncedReaderFastNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = _node_executable()
        if not cls.node:
            raise unittest.SkipTest("Node.js is not available for synced-reader JS tests")
        cls.source = READER_HTML.read_text(encoding="utf-8")
        helper_names = [
            "connectedTypesetTargets",
            "scheduleMathJaxRetry",
            "flushTypesetQueue",
            "typesetTargets",
            "requestImageWindowIfNeeded",
        ]
        cls.js_helpers = "\n\n".join(
            block for name in helper_names if (block := _extract_function(cls.source, name))
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

    def test_image_window_request_rechecks_page_state_before_notify(self):
        self.run_js(
            r"""
            let pages = [{ slideNumber: 1, imageAvailable: true, image: '' }];
            let deckId = 9;
            let lastPositionNotifyKey = '';
            let positionNotifyTimer = null;
            const IMAGE_WINDOW_NOTIFY_IDLE_MS = 0;
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


if __name__ == "__main__":
    unittest.main()
