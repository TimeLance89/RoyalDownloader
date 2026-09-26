import { createScope } from "../../core/lifecycle.js";

/** Class-based shell dialogs; opening owns focus, keyboard and async action scope. */
export function createDialog(root, { initialFocus, onClose = () => {}, dismissible = true } = {}) {
  const document = root.ownerDocument;
  let scope;
  let returnFocus;
  function close(restoreFocus = true) {
    if (!scope) return;
    scope.dispose(); scope = null;
    root.classList.add("hidden");
    onClose();
    if (restoreFocus && returnFocus?.isConnected) returnFocus.focus();
    returnFocus = null;
  }
  return {
    close,
    open(trigger = document.activeElement) {
      if (scope?.active) return scope;
      scope = createScope();
      returnFocus = trigger;
      root.classList.remove("hidden");
      scope.listen(root, "click", event => { if (dismissible && event.target === root) close(); });
      scope.listen(document, "keydown", event => {
        if (dismissible && event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close(); return; }
        if (event.key !== "Tab") return;
        const focusable = [...root.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
          .filter(element => element.getClientRects().length);
        const first = focusable[0], last = focusable.at(-1);
        if (!first) { event.preventDefault(); return; }
        if (event.shiftKey && (document.activeElement === first || !root.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !root.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
      }, true);
      scope.frame(() => (initialFocus?.() || root.querySelector("button"))?.focus());
      return scope;
    },
    unmount() { close(false); },
  };
}
