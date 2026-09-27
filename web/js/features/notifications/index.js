import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { notificationCount } from "./model.js";
import { createNotificationView } from "./view.js";
import { notificationApi } from "./api.js";

export function createNotifications(root, { getSnapshot, check, onSnapshot, openEntry, openLibrary, coverUrl, subscriptionMonogram, libraryCheckedLabel, requests = notificationApi, getSnapshotVersion = () => 0 }) {
  const document = root.ownerDocument;
  const find = id => root.querySelector(`#${id}`);
  const ui = { filter: "all", reading: "", feedback: "", feedbackError: false };
  let shell;
  let actions;
  let checking = false;
  if (!find("notif-issue-badge")) {
    const badge = document.createElement("span");
    badge.id = "notif-issue-badge"; badge.className = "notif-issue-badge hidden";
    badge.textContent = "!"; badge.setAttribute("aria-hidden", "true");
    find("notif-bell").appendChild(badge);
  }
  function busy() {
    const snapshot = getSnapshot();
    return checking || Boolean(snapshot.checkRunning || notificationCount(snapshot.health?.checking_count) || snapshot.items.some(entry => entry.checking));
  }
  const view = createNotificationView(root, {
    getSnapshot, ui, coverUrl, subscriptionMonogram, libraryCheckedLabel,
    inboxCheckBusy: busy, closeNotifDropdown: close, openWatchlistEntry: openEntry,
    runNotificationCheck: runCheck, markNotificationDownloadsRead: markRead,
  });
  function refresh() { if (shell?.active) view.refresh(Boolean(actions?.active)); }
  function close(restoreFocus = false) {
    actions?.dispose(); actions = null; checking = false; ui.reading = "";
    view.unmount();
    find("notif-dropdown").classList.add("hidden");
    find("notif-bell").setAttribute("aria-expanded", "false");
    if (restoreFocus) find("notif-bell").focus({ preventScroll: true });
  }
  function open() {
    if (!shell?.active) return;
    if (!actions?.active) actions = createScope();
    find("notif-dropdown").classList.remove("hidden");
    find("notif-bell").setAttribute("aria-expanded", "true");
    refresh();
  }
  async function runCheck(slugs) {
    const current = actions;
    if (!current?.active || busy()) return;
    checking = true; ui.feedback = ""; refresh();
    try {
      const data = await check(slugs || null, { signal: current.signal });
      if (!current.active) return;
      ui.feedback = data?.health?.error ? String(data.health.error) : "Prüfung abgeschlossen. Meldungen wurden aktualisiert.";
      ui.feedbackError = Boolean(data?.health?.error);
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      ui.feedback = `Prüfung fehlgeschlagen: ${error.message || error}`; ui.feedbackError = true;
    } finally { if (current.active) { checking = false; refresh(); } }
  }
  async function markRead(entry) {
    const current = actions;
    if (!current?.active || ui.reading) return;
    ui.reading = entry.base_slug; ui.feedback = ""; refresh();
    try {
      await requests.acknowledge(entry, current.signal);
      if (!current.active) return;
      const version = getSnapshotVersion();
      const data = await requests.snapshot(current.signal);
      if (!current.active) return;
      if (getSnapshotVersion() === version) onSnapshot(data);
      ui.feedback = `Download-Meldungen für ${entry.title} als gelesen markiert.`; ui.feedbackError = false;
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      ui.feedback = `Lesestatus konnte nicht aktualisiert werden: ${error.message || error}`; ui.feedbackError = true;
    } finally { if (current.active) { ui.reading = ""; refresh(); } }
  }
  return {
    refresh, open, close,
    mount() {
      if (shell?.active) return;
      shell = createScope();
      shell.listen(find("notif-bell"), "click", event => { event.stopPropagation(); if (actions?.active) close(); else open(); });
      shell.listen(document, "click", event => {
        // A row action may replace its own DOM before the event bubbles here.
        const inside = event.composedPath ? event.composedPath().includes(root) : root.contains(event.target);
        if (!inside) close();
      });
      shell.listen(find("notif-close"), "click", () => close(true));
      shell.listen(find("notif-refresh"), "click", () => runCheck(null));
      shell.listen(find("notif-library"), "click", () => { close(); openLibrary(); });
      root.querySelectorAll("[data-notif-filter]").forEach(button => shell.listen(button, "click", event => {
        event.stopPropagation(); ui.filter = button.dataset.notifFilter || "all"; refresh();
      }));
      refresh();
    },
    unmount() { close(); shell?.dispose(); shell = null; },
  };
}
