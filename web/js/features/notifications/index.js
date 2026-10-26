import { createInboxDismissals } from "./dismissals.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { notificationCount } from "./model.js";
import { createNotificationView } from "./view.js";
import { notificationApi } from "./api.js";
import { createSourceIssueInbox } from "./source-issues.js";
import { createAnnouncementInbox } from "../announcements/inbox.js";

export function createNotifications(root, { getSnapshot, check, onSnapshot, openEntry, openLibrary, coverUrl, subscriptionMonogram, libraryCheckedLabel, requests = notificationApi, getSnapshotVersion = () => 0, beforeOpen = () => {}, getUser = () => null }) {
  const document = root.ownerDocument;
  const find = id => root.querySelector(`#${id}`);
  const ui = { filter: "all", reading: "", feedback: "", feedbackError: false };
  let shell;
  let actions;
  let checking = false, opener = null;
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
  const dismissals = createInboxDismissals({ getUser, onChange: () => refresh() });
  const dismissalOptions = { hidden: key => dismissals.has(key), dismiss: removeMessages };
  const view = createNotificationView(root, { ...dismissalOptions,
    getSnapshot, ui, coverUrl, subscriptionMonogram, libraryCheckedLabel,
    inboxCheckBusy: busy, closeNotifDropdown: close, openWatchlistEntry: openEntry,
    runNotificationCheck: runCheck, markNotificationDownloadsRead: markRead,
  });
  const announcements = createAnnouncementInbox(root, { ...dismissalOptions,
    onChange: () => refresh(), getFilter: () => ui.filter, isOpen: () => Boolean(actions?.active),
  });
  const sourceIssues = createSourceIssueInbox(root, { ...dismissalOptions,
    onChange: () => refresh(), getFilter: () => ui.filter, isOpen: () => Boolean(actions?.active), getUser,
  });
  function refresh() {
    if (!shell?.active) return;
    view.refresh(Boolean(actions?.active));
    announcements.render();
    sourceIssues.render();
    const count = Number([...root.querySelectorAll("[data-notif-filter]")].find(node => node.dataset.notifFilter === "all")?.querySelector(".notif-filter-count")?.textContent) || 0;
    if (!busy()) find("notif-summary").textContent = count ? `${count} ${count === 1 ? "Eintrag" : "Einträge"}` : "Keine Meldungen";
    const total = Number(find("notif-badge").textContent) || 0;
    const label = total ? `${total} ${total === 1 ? "Hinweis" : "Hinweise"}` : "Alles aktuell";
    find("notif-trigger-label").textContent = label;
    find("notif-bell").setAttribute("aria-label", `Abo-Inbox öffnen: ${label}`);
    document.querySelectorAll("[data-notif-mobile-summary]").forEach(node => { node.textContent = label; });
    document.querySelectorAll("[data-notif-mobile-badge]").forEach(node => { node.textContent = String(total); node.classList.toggle("hidden", !total); });
    document.getElementById("mobile-more-toggle")?.setAttribute("aria-label", total ? `Mehr, Abo-Inbox: ${label}` : "Mehr");
    root.querySelectorAll(".notif-item-dismiss").forEach(button => { button.disabled = Boolean(ui.removing); });
    if (find("notif-dismiss-all")) find("notif-dismiss-all").disabled = !visibleKeys().length || Boolean(ui.removing);
  }
  function visibleKeys() { return [...view.keys(), ...announcements.keys(), ...sourceIssues.keys()]; }
  async function removeMessages(keys) {
    if (ui.removing || !shell?.active) return;
    const current = shell;
    ui.removing = true; ui.feedback = ""; refresh();
    try {
      await dismissals.remove(keys);
      if (!current.active) return;
      ui.feedback = "Meldungen entfernt. Abos und Downloads laufen weiter."; ui.feedbackError = false;
    } catch (error) {
      if (!current.active || isAbortError(error)) return;
      ui.feedback = `Entfernen fehlgeschlagen: ${error.message || error}`; ui.feedbackError = true;
    } finally { if (current.active) { ui.removing = false; refresh(); } }
  }
  function close(restoreFocus = false) {
    actions?.dispose(); actions = null; checking = false; ui.reading = "";
    view.unmount();
    find("notif-dropdown").classList.add("hidden");
    find("notif-bell").setAttribute("aria-expanded", "false");
    document.querySelectorAll("[data-notifications-open]").forEach(trigger => trigger.setAttribute("aria-expanded", "false"));
    if (restoreFocus) {
      const target = opener?.getClientRects?.()?.length ? opener
        : opener?.hasAttribute("data-notifications-open") ? document.getElementById("mobile-more-toggle") : find("notif-bell");
      target?.focus({ preventScroll: true });
    }
  }
  function open(trigger = null) {
    if (!shell?.active) return;
    beforeOpen();
    opener = trigger || find("notif-bell");
    if (!actions?.active) actions = createScope();
    find("notif-dropdown").classList.remove("hidden");
    find("notif-bell").setAttribute("aria-expanded", "true");
    document.querySelectorAll("[data-notifications-open]").forEach(button => button.setAttribute("aria-expanded", "true"));
    refresh();
    void announcements.reload();
    void sourceIssues.reload();
    void dismissals.reload().catch(() => {});
    if (document.defaultView?.matchMedia?.("(max-width: 820px)").matches) find("notif-close").focus({ preventScroll: true });
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
      dismissals.mount();
      if (document.defaultView) void dismissals.reload().catch(() => {});
      shell.listen(find("notif-bell"), "click", event => { event.stopPropagation(); if (actions?.active) close(); else open(); });
      document.querySelectorAll("[data-notifications-open]").forEach(trigger => shell.listen(trigger, "click", event => {
        event.stopPropagation(); open(trigger);
      }));
      shell.listen(document, "keydown", event => {
        if (event.key === "Escape" && actions?.active) { event.preventDefault(); close(true); }
      });
      shell.listen(document, "click", event => {
        // A row action may replace its own DOM before the event bubbles here.
        const inside = event.composedPath ? event.composedPath().includes(root) : root.contains(event.target);
        if (!inside) close();
      });
      shell.listen(find("notif-close"), "click", () => close(true));
      if (find("notif-dismiss-all")) shell.listen(find("notif-dismiss-all"), "click", () => { void removeMessages(visibleKeys()); });
      shell.listen(find("notif-refresh"), "click", () => runCheck(null));
      shell.listen(find("notif-library"), "click", () => { close(); openLibrary(); });
      root.querySelectorAll("[data-notif-filter]").forEach(button => shell.listen(button, "click", event => {
        event.stopPropagation(); ui.filter = button.dataset.notifFilter || "all"; refresh();
      }));
      announcements.mount();
      sourceIssues.mount();
      refresh();
    },
    unmount() { ui.removing = false; dismissals.unmount(); sourceIssues.unmount(); announcements.unmount(); close(); shell?.dispose(); shell = null; },
  };
}
