import os
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = APP_ROOT / "app.py"
SHORTCUT_JS = APP_ROOT / "components" / "enter_submit_shortcut.js"
READER_HTML = APP_ROOT / "components" / "synced_reader" / "index.html"


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


class StreamlitEnterSubmitShortcutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = _node_executable()
        if not cls.node:
            raise unittest.SkipTest("Node.js is not available for shortcut JS tests")

    def run_js(self, body):
        script = textwrap.dedent(body)
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

    def test_app_loads_global_enter_submit_shortcut(self):
        source = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("enter_submit_shortcut.js", source)
        self.assertIn("ENTER_SUBMIT_SHORTCUT_SCRIPT", source)

    def test_streamlit_shortcut_submits_enter_without_hijacking_delete(self):
        self.run_js(
            r"""
            const shortcut = require('./components/enter_submit_shortcut.js');

            const enter = {
              key: 'Enter',
              shiftKey: false,
              ctrlKey: false,
              metaKey: false,
              altKey: false,
              isComposing: false,
              keyCode: 13,
            };
            if (!shortcut.shouldSubmitOnEnter(enter)) {
              throw new Error('plain Enter should submit');
            }
            if (shortcut.shouldSubmitOnEnter({ ...enter, shiftKey: true })) {
              throw new Error('Shift+Enter should keep textarea newline behavior');
            }
            if (shortcut.shouldSubmitOnEnter({ ...enter, isComposing: true })) {
              throw new Error('IME composition Enter should not submit');
            }
            if (shortcut.shouldSubmitOnEnter({ ...enter, keyCode: 229 })) {
              throw new Error('IME keyCode 229 should not submit');
            }
            if (!shortcut.buttonLooksLikeEnterAction({ innerText: '保存为项目默认 API' })) {
              throw new Error('save button should be an Enter action');
            }
            if (!shortcut.buttonLooksLikeEnterAction({ textContent: '发送测试请求' })) {
              throw new Error('send button should be an Enter action');
            }
            if (shortcut.buttonLooksLikeEnterAction({ innerText: '删除这份资料' })) {
              throw new Error('delete button must not be triggered by Enter');
            }
            """
        )

    def test_streamlit_shortcut_blurs_pending_input_before_clicking_action(self):
        self.run_js(
            r"""
            const shortcut = require('./components/enter_submit_shortcut.js');

            const timers = [];
            const doc = {
              body: { tagName: 'BODY' },
              defaultView: {
                Event: function(type) { this.type = type; },
                getComputedStyle: () => ({ display: 'block', visibility: 'visible' }),
                setTimeout: (callback, delay) => {
                  timers.push({ callback, delay });
                  return timers.length;
                },
              },
            };
            let clicked = 0;
            let blurred = 0;
            const action = {
              disabled: false,
              innerText: '解锁并使用本地 API Key',
              ownerDocument: doc,
              getAttribute: () => null,
              click: () => { clicked += 1; },
            };
            const scope = {
              parentElement: doc.body,
              querySelectorAll: selector => selector === 'button' ? [action] : [],
            };
            const dispatched = [];
            const target = {
              disabled: false,
              readOnly: false,
              ownerDocument: doc,
              parentElement: scope,
              closest(selector) {
                if (selector.includes('input')) return this;
                if (selector.includes('data-intp-enter-submit-disabled')) return null;
                return null;
              },
              compareDocumentPosition: () => 4,
              dispatchEvent: event => dispatched.push(event.type),
              blur: () => { blurred += 1; },
            };
            const event = {
              key: 'Enter',
              shiftKey: false,
              ctrlKey: false,
              metaKey: false,
              altKey: false,
              isComposing: false,
              keyCode: 13,
              target,
              preventDefault() {},
              stopPropagation() {},
              stopImmediatePropagation() {},
            };

            if (!shortcut.handleEnterSubmit(event)) {
              throw new Error('Enter event should be handled');
            }
            if (blurred !== 1) {
              throw new Error(`expected input blur before action click, got ${blurred}`);
            }
            if (!dispatched.includes('input') || !dispatched.includes('change')) {
              throw new Error(`expected input/change events, got ${dispatched.join(',')}`);
            }
            if (clicked !== 0) {
              throw new Error('action should not click synchronously before Streamlit applies the value');
            }
            if (timers.length !== 1 || timers[0].delay < 75) {
              throw new Error(`expected delayed click, got ${timers.length ? timers[0].delay : 'none'}`);
            }
            timers[0].callback();
            if (clicked !== 1) {
              throw new Error(`expected delayed action click, got ${clicked}`);
            }
            """
        )

    def test_installed_listener_uses_latest_shortcut_api(self):
        self.run_js(
            r"""
            const shortcut = require('./components/enter_submit_shortcut.js');

            let windowListener = null;
            let documentListener = null;
            let oldCalls = 0;
            let latestCalls = 0;
            const win = {
              __intpEnterSubmitShortcut: {
                handleEnterSubmit: () => { oldCalls += 1; },
              },
              addEventListener: (type, listener) => {
                if (type === 'keydown') windowListener = listener;
              },
              document: {
                addEventListener: (type, listener) => {
                  if (type === 'keydown') documentListener = listener;
                },
              },
            };

            if (!shortcut.installEnterSubmitShortcut(win)) {
              throw new Error('expected listener installation');
            }
            win.__intpEnterSubmitShortcut = {
              handleEnterSubmit: () => { latestCalls += 1; },
            };
            windowListener({ key: 'Enter' });
            documentListener({ key: 'Enter' });
            if (oldCalls !== 0 || latestCalls !== 2) {
              throw new Error(`listener used stale API: old=${oldCalls} latest=${latestCalls}`);
            }
            """
        )


class SyncedReaderEnterSubmitShortcutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = _node_executable()
        if not cls.node:
            raise unittest.SkipTest("Node.js is not available for synced-reader JS tests")
        cls.source = READER_HTML.read_text(encoding="utf-8")
        helper_names = ["shouldSubmitInputOnEnter", "submitInputOnEnter"]
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

    def test_reader_helper_submits_plain_enter_and_preserves_shift_enter(self):
        self.run_js(
            r"""
            let prevented = 0;
            let stopped = 0;
            let submitted = 0;
            const event = {
              key: 'Enter',
              shiftKey: false,
              ctrlKey: false,
              metaKey: false,
              altKey: false,
              isComposing: false,
              keyCode: 13,
              preventDefault() { prevented += 1; },
              stopPropagation() { stopped += 1; },
            };

            if (!submitInputOnEnter(event, () => { submitted += 1; })) {
              throw new Error('plain Enter should be handled');
            }
            if (submitted !== 1 || prevented !== 1 || stopped !== 1) {
              throw new Error(`bad submit handling: ${submitted}/${prevented}/${stopped}`);
            }
            if (submitInputOnEnter({ ...event, shiftKey: true }, () => { submitted += 1; })) {
              throw new Error('Shift+Enter should not submit');
            }
            if (submitInputOnEnter({ ...event, isComposing: true }, () => { submitted += 1; })) {
              throw new Error('IME composition should not submit');
            }
            """
        )

    def test_reader_wires_chat_and_note_inputs_to_enter_submit(self):
        self.assertIn("submitInputOnEnter(event, sendCanvasQuestion)", self.source)
        self.assertIn("childChatStack.addEventListener('keydown'", self.source)
        self.assertIn("sendChildQuestion(input.dataset.childInput)", self.source)
        self.assertIn("noteRoot.addEventListener('keydown'", self.source)
        self.assertIn("data-note-slide", self.source)
        self.assertIn("saveEditedExplanation(Number(editor.dataset.noteSlide || 0))", self.source)


if __name__ == "__main__":
    unittest.main()
