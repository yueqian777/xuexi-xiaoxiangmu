(function(root) {
  const INSTALL_FLAG = '__intpEnterSubmitShortcutInstalled';
  const LISTENER_KEY = '__intpEnterSubmitShortcutListener';
  const ACTION_CLICK_DELAY_MS = 100;
  const EDITABLE_SELECTOR = [
    'textarea',
    'input:not([type])',
    'input[type="email"]',
    'input[type="number"]',
    'input[type="password"]',
    'input[type="search"]',
    'input[type="tel"]',
    'input[type="text"]',
    'input[type="url"]',
  ].join(',');
  const ACTION_WORDS = [
    '保存',
    '发送',
    '提交',
    '更新',
    '登录',
    '注册',
    '创建',
    '解锁',
    '加入',
    '转化',
    '导入',
    '查询',
    '应用',
    '标记',
    '生成',
    '测速',
    '测试',
    '问当前模型',
  ];
  const DANGER_WORDS = ['删除', '清空', '移除', '重置', '停止', '取消'];

  function shouldSubmitOnEnter(event) {
    return (
      event &&
      event.key === 'Enter' &&
      !event.shiftKey &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey &&
      !event.isComposing &&
      event.keyCode !== 229
    );
  }

  function editableEnterTarget(target) {
    if (!target?.closest) return null;
    const editable = target.closest(EDITABLE_SELECTOR);
    if (!editable || editable.disabled || editable.readOnly) return null;
    if (editable.closest('[data-intp-enter-submit-disabled="true"]')) return null;
    return editable;
  }

  function buttonText(button) {
    return String(button?.innerText || button?.textContent || '')
      .replace(/\s+/g, '')
      .trim();
  }

  function buttonIsEnabled(button) {
    if (!button || button.disabled) return false;
    if (button.getAttribute?.('aria-disabled') === 'true') return false;
    const style = button.ownerDocument?.defaultView?.getComputedStyle?.(button);
    if (style && (style.display === 'none' || style.visibility === 'hidden')) return false;
    return true;
  }

  function buttonLooksLikeEnterAction(button) {
    const text = buttonText(button);
    if (!text) return false;
    if (DANGER_WORDS.some(word => text.includes(word))) return false;
    return ACTION_WORDS.some(word => text.includes(word));
  }

  function firstEnabledButton(scope) {
    const buttons = Array.from(scope?.querySelectorAll?.('button') || []);
    return buttons.find(buttonIsEnabled) || null;
  }

  function firstNearbyActionButton(target) {
    let scope = target?.parentElement || null;
    const doc = target?.ownerDocument || null;
    while (scope && scope !== doc?.body) {
      const buttons = Array.from(scope.querySelectorAll?.('button') || [])
        .filter(buttonIsEnabled)
        .filter(buttonLooksLikeEnterAction)
        .filter(button => {
          if (!target.compareDocumentPosition) return true;
          return Boolean(target.compareDocumentPosition(button) & 4);
        });
      if (buttons.length) return buttons[0];
      scope = scope.parentElement;
    }
    return null;
  }

  function findStreamlitEnterAction(target) {
    const form = target?.closest?.('form, [data-testid="stForm"]');
    if (form) return firstEnabledButton(form);
    return firstNearbyActionButton(target);
  }

  function dispatchWidgetValue(target) {
    const doc = target?.ownerDocument;
    const view = doc?.defaultView || root;
    const EventCtor = view.Event || Event;
    target?.dispatchEvent?.(new EventCtor('input', { bubbles: true }));
    target?.dispatchEvent?.(new EventCtor('change', { bubbles: true }));
  }

  function clickActionAfterWidgetSync(target, action) {
    dispatchWidgetValue(target);
    target?.blur?.();
    const view = target?.ownerDocument?.defaultView || root;
    view.setTimeout(() => action.click(), ACTION_CLICK_DELAY_MS);
  }

  function handleEnterSubmit(event) {
    if (!shouldSubmitOnEnter(event)) return false;
    const target = editableEnterTarget(event.target);
    if (!target) return false;
    const action = findStreamlitEnterAction(target);
    if (!action) return false;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === 'function') {
      event.stopImmediatePropagation();
    }
    clickActionAfterWidgetSync(target, action);
    return true;
  }

  function resolveRootWindow() {
    if (typeof window === 'undefined') return root;
    try {
      const rootWindow = window.parent || window;
      void rootWindow.document;
      return rootWindow;
    } catch {
      return window;
    }
  }

  function installEnterSubmitShortcut(rootWindow) {
    const win = rootWindow || resolveRootWindow();
    const doc = win?.document;
    if (!win || !doc) return false;
    if (win[LISTENER_KEY]) return false;
    win[INSTALL_FLAG] = true;
    const listener = event => win.__intpEnterSubmitShortcut?.handleEnterSubmit?.(event);
    win[LISTENER_KEY] = listener;
    win.addEventListener?.('keydown', listener, true);
    doc.addEventListener?.('keydown', listener, true);
    return true;
  }

  const api = {
    buttonLooksLikeEnterAction,
    editableEnterTarget,
    findStreamlitEnterAction,
    handleEnterSubmit,
    installEnterSubmitShortcut,
    shouldSubmitOnEnter,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.__intpEnterSubmitShortcut = api;

  if (typeof window !== 'undefined' && window.document) {
    installEnterSubmitShortcut(resolveRootWindow());
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
