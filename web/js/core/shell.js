import { api } from "./api.js";
import { createScope } from "./lifecycle.js";

/** Session-owned shell menus, shortcuts and persistent queue controls. */
export function createShell(document, {
  switchTab, openMobileQueue, closeMobileQueue, toggleDesktopQueue, closeMediaModal,
  openWatchModeModal, handleMediaModalKeydown, closeNotifications, setQueueDockExpanded,
  refreshQueueUiAfterChange, renderSerienstreamHealth, setDownloadState, getDownloadPercent, openDirectory,
  client = api,
}) {
  let scope = null;
  const pending = new Set();
  async function command(url, accept) {
    if (!scope?.active || pending.has(url)) return;
    const owner = scope; pending.add(url);
    try {
      const response = await client.post(url, undefined, { signal: owner.signal });
      if (owner.active) accept(response);
    } catch (error) {
      if (owner.active) setDownloadState("error", "Aktion fehlgeschlagen", error.message, getDownloadPercent());
    } finally { if (owner.active) pending.delete(url); }
  }
  function setNavigationMenuOpen(menu, open, { restoreFocus = false } = {}) {
    const trigger = menu.querySelector(".nav-menu-trigger");
    const popover = menu.querySelector(".nav-menu-popover");
    if (!trigger || !popover) return;
    menu.classList.toggle("is-open", open);
    trigger.classList.toggle("is-open", open);
    trigger.setAttribute("aria-expanded", String(open));
    popover.hidden = !open;
    popover.inert = !open;
    if (!open && restoreFocus) trigger.focus();
  }

  function closeNavigationMenus({ restoreFocus = false, except = null } = {}) {
    document.querySelectorAll("[data-nav-menu]").forEach((menu) => {
      if (menu !== except) setNavigationMenuOpen(menu, false, { restoreFocus });
    });
    const anyMobileMenuOpen = Boolean(document.querySelector('[data-nav-menu="mobile"].is-open'));
    const scrim = document.querySelector("[data-nav-menu-scrim]");
    if (scrim) scrim.hidden = !anyMobileMenuOpen;
  }

  function initNavigationMenus() {
    document.querySelectorAll(".tabs [data-tab], .mobile-tabs [data-tab]").forEach((button) => {
      scope.listen(button, "click", () => switchTab(button.dataset.tab));
    });
    document.querySelectorAll("[data-nav-menu]").forEach((menu) => {
      const trigger = menu.querySelector(".nav-menu-trigger");
      const popover = menu.querySelector(".nav-menu-popover");
      if (!trigger || !popover) return;
      popover.inert = true;
      scope.listen(trigger, "click", (event) => {
        event.stopPropagation();
        const open = !menu.classList.contains("is-open");
        closeNavigationMenus({ except: menu });
        setNavigationMenuOpen(menu, open);
        const scrim = document.querySelector("[data-nav-menu-scrim]");
        if (scrim) scrim.hidden = !open || menu.dataset.navMenu !== "mobile";
      });
      scope.listen(popover, "click", (event) => {
        if (!event.target.closest("[data-tab], [data-mood-open]")) return;
        closeNavigationMenus();
      });
    });
    scope.listen(document.querySelector("[data-nav-menu-scrim]"), "click", () => closeNavigationMenus());
    scope.listen(document, "pointerdown", (event) => {
      if (event.target.closest("[data-nav-menu], [data-nav-menu-scrim]")) return;
      closeNavigationMenus();
    });
    scope.listen(document, "keydown", (event) => {
      if (event.key !== "Escape") return;
      const openMenu = document.querySelector("[data-nav-menu].is-open");
      if (!openMenu) return;
      event.preventDefault();
      closeNavigationMenus({ restoreFocus: true });
    });
    scope.listen(document, "keydown", (event) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "k") return;
      const input = document.getElementById("global-search-input");
      if (!input) return;
      event.preventDefault();
      document.getElementById("global-search-shell").classList.add("is-expanded");
      input.focus();
    });
    scope.listen(document.defaultView, "resize", () => closeNavigationMenus());
  }

  function mount() {
    if (scope?.active) return;
    scope = createScope(); initNavigationMenus();
    document.getElementById("serienstream-retry").disabled = false;
  scope.listen(document.getElementById("mobile-queue-btn"), "click", openMobileQueue);
  scope.listen(document.getElementById("mobile-queue-close"), "click", closeMobileQueue);
  scope.listen(document.getElementById("mobile-queue-backdrop"), "click", closeMobileQueue);
  scope.listen(document.getElementById("queue-dock-toggle"), "click", toggleDesktopQueue);
  document.querySelectorAll("[data-modal-close]").forEach((button) => {
    scope.listen(button, "click", () => closeMediaModal(button.dataset.modalClose));
  });
  scope.listen(document.getElementById("series-watch-btn"), "click", () => openWatchModeModal());
  scope.listen(document.getElementById("series-subscriptions-manage"), "click", () => switchTab("bibliothek"));
  scope.listen(document, "keydown", (event) => {
    if (
      event.key !== "/"
      || event.ctrlKey
      || event.metaKey
      || event.altKey
      || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")
      || document.activeElement?.isContentEditable
    ) return;
    const input = document.getElementById("global-search-input");
    if (!input) return;
    event.preventDefault();
    document.getElementById("global-search-shell").classList.add("is-expanded");
    input.focus();
  });
  scope.listen(document, "keydown", (event) => {
    if (handleMediaModalKeydown(event)) return;
    if (event.key !== "Escape") return;
    closeNotifications();
    setQueueDockExpanded(false);
    closeMobileQueue();
  });
  scope.listen(document.getElementById("queue-clear"), "click", () => command("/api/queue/clear", refreshQueueUiAfterChange));
  scope.listen(document.getElementById("cancel-btn"), "click", () => command("/api/download/cancel", response => {
    refreshQueueUiAfterChange(response);
    setDownloadState("cancelled", "Abgebrochen", "Downloads wurden gestoppt", getDownloadPercent());
  }));
  scope.listen(document.getElementById("serienstream-retry"), "click", async () => {
    const owner = scope, button = document.getElementById("serienstream-retry");
    if (button.disabled) return;
    button.disabled = true;
    try {
      const response = await client.post("/api/providers/serienstream/retry", undefined, { signal: owner.signal });
      if (owner.active) renderSerienstreamHealth(response.provider || {});
    } catch (error) {
      if (owner.active) console.warn("SerienStream-Probe konnte nicht gestartet werden:", error);
    } finally {
      if (owner.active) owner.timeout(() => { button.disabled = false; }, 1500);
    }
  });
  scope.listen(document.getElementById("settings-btn"), "click", () => switchTab("einstellungen"));
  for (const [buttonId, inputId] of [
    ["browse-dir-btn", "save-path"], ["browse-series-btn", "series-path"],
  ]) {
    scope.listen(document.getElementById(buttonId), "click", event => {
      openDirectory(document.getElementById(inputId), event.currentTarget);
    });
  }
  }
  function unmount() { scope?.dispose(); scope = null; pending.clear(); closeNavigationMenus(); }
  return { mount, unmount, closeMenus: closeNavigationMenus, setMenuOpen: setNavigationMenuOpen };
}
