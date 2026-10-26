import { inboxKey } from "./dismissals.js";
import { api } from "../../core/api.js";

/** Durable administrator incidents, independent of optional status push notices. */
export function createSourceIssueInbox(root, { onChange, getFilter, isOpen, getUser, hidden = () => false, dismiss = async () => {}, client = api }) {
  const document = root.ownerDocument;
  let expanded = false;
  const key = item => inboxKey("source", item.id);
  const visibleItems = () => items.filter(item => !hidden(key(item)));
  let items = [], owner = "", mounted = false, controller = null, timer = null, reading = "";
  const userId = () => getUser()?.role === "admin" ? String(getUser()?.id || "") : "";
  async function reload() {
    if (!mounted) return;
    const id = userId();
    if (id !== owner) { items = []; owner = id; onChange(); }
    controller?.abort();
    if (!id) return;
    const current = controller = new AbortController();
    try {
      const data = await client.get("/api/providers/incidents", {
        signal: current.signal, headers: { "X-Royal-Profile": id },
      });
      if (!mounted || current !== controller || userId() !== id) return;
      items = Array.isArray(data.items) ? data.items.slice(0, 100) : [];
      onChange();
    } catch (error) {
      if (!current.signal.aborted && [401, 403, 409].includes(error.status)) { items = []; onChange(); }
    }
  }
  async function read(item) {
    const id = userId(), current = controller;
    if (!mounted || !id || id !== owner || reading || !current) return;
    reading = item.id;
    try {
      await client.post("/api/providers/incidents/" + encodeURIComponent(item.id) + "/read", {}, {
        signal: current.signal, headers: { "X-Royal-Profile": id },
      });
      if (!mounted || current.signal.aborted || userId() !== id) return;
      items = items.map(row => row.id === item.id ? { ...row, read: true } : row);
      onChange();
    } catch { /* Keep the unread incident visible if acknowledgement failed. */ }
    finally { reading = ""; }
  }
  function render() {
    root.querySelector(".source-issue-group")?.remove();
    if (!mounted || !owner || owner !== userId()) return;
    const visible = visibleItems();
    if (!visible.length) return;
    const unread = visible.some(item => !item.read) ? 1 : 0;
    const badge = root.querySelector("#notif-badge");
    if (badge) {
      const total = (Number(badge.textContent) || 0) + unread;
      badge.textContent = String(total); badge.classList.toggle("hidden", total === 0);
      root.querySelector("#notif-bell")?.classList.toggle("is-active", total > 0);
    }
    for (const filter of ["all", "issue"]) {
      const count = root.querySelector('[data-notif-filter="' + filter + '"] .notif-filter-count');
      if (count) count.textContent = String((Number(count.textContent) || 0) + 1);
    }
    if (!isOpen() || !["all", "issue"].includes(getFilter())) return;
    const list = root.querySelector("#notif-list");
    if (!list) return;
    list.querySelector(".notif-empty")?.remove();
    const group = document.createElement("details");
    group.className = "source-issue-group"; group.open = expanded;
    group.addEventListener("toggle", () => { if (group.isConnected) expanded = group.open; });
    const summary = document.createElement("summary");
    summary.textContent = `Quellenprüfung · ${visible.length} ${visible.length === 1 ? "Hinweis" : "Hinweise"}`;
    const hint = document.createElement("p");
    hint.textContent = "Technische Prüfhinweise. Sie bedeuten nicht automatisch, dass deine Downloads ausfallen. Details unter Quellen & Verfügbarkeit.";
    hint.className = "notif-context";
    group.append(summary, hint);
    for (const item of visible) {
      const row = document.createElement("article"); row.className = "source-issue-row";
      const title = document.createElement("strong"); title.textContent = item.label;
      const actions = document.createElement("div"); actions.className = "notif-item-actions";
      if (!item.read) {
        const readButton = document.createElement("button");
        readButton.type = "button"; readButton.textContent = "Als gelesen"; readButton.dataset.sourceRead = item.id;
        readButton.addEventListener("click", async () => { readButton.disabled = true; await read(item); if (readButton.isConnected) readButton.disabled = false; });
        actions.append(readButton);
      }
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "notif-item-dismiss"; remove.textContent = "Entfernen";
      remove.setAttribute("aria-label", `Quellenhinweis ${item.label} entfernen`);
      remove.addEventListener("click", () => { void dismiss([key(item)]); });
      actions.append(remove); row.append(title, actions); group.append(row);
    }
    list.append(group);
  }
  return {
    render, reload,
    keys: () => owner && owner === userId() && ["all", "issue"].includes(getFilter()) ? visibleItems().map(key) : [],
    mount() {
      if (mounted) return;
      mounted = true;
      if (!document.defaultView) return;
      void reload();
      timer = setInterval(() => { if (!document.hidden) void reload(); }, 60_000);
      timer?.unref?.();
    },
    unmount() {
      mounted = false; controller?.abort(); controller = null;
      clearInterval(timer); timer = null; items = []; owner = ""; reading = "";
    },
  };
}
