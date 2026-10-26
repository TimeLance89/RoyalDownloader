import { api } from "../../core/api.js";

/** Durable administrator incidents, independent of optional status push notices. */
export function createSourceIssueInbox(root, { onChange, getFilter, isOpen, getUser, client = api }) {
  const document = root.ownerDocument;
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
    const unread = items.filter(item => !item.read).length;
    const badge = root.querySelector("#notif-badge");
    if (!badge) return;
    const total = (Number(badge.textContent) || 0) + unread;
    badge.textContent = String(total);
    badge.classList.toggle("hidden", total === 0);
    root.querySelector("#notif-bell")?.classList.toggle("is-active", total > 0);
    for (const [filter, count] of [["all", items.length], ["new", unread], ["issue", items.length]]) {
      const node = root.querySelector('[data-notif-filter="' + filter + '"] .notif-filter-count');
      if (node) node.textContent = String((Number(node.textContent) || 0) + count);
    }
    document.querySelectorAll("[data-notif-mobile-badge]").forEach(node => {
      node.textContent = String(total); node.classList.toggle("hidden", total === 0);
    });
    if (unread) {
      const label = total + " Hinweise";
      const trigger = root.querySelector("#notif-trigger-label");
      if (trigger) trigger.textContent = label;
      root.querySelector("#notif-bell")?.setAttribute("aria-label", "Abo-Inbox öffnen: " + label);
      document.querySelectorAll("[data-notif-mobile-summary]").forEach(node => { node.textContent = label; });
    }
    if (!isOpen() || !["all", "new", "issue"].includes(getFilter())) return;
    const visible = items.filter(item => getFilter() !== "new" || !item.read);
    const list = root.querySelector("#notif-list");
    if (!list || !visible.length) return;
    list.querySelector(".notif-empty")?.remove();
    const group = document.createElement("section");
    group.className = "source-issue-group royal-announcement-group";
    const heading = document.createElement("h3");
    heading.className = "royal-announcement-heading";
    heading.textContent = "Quellen benötigen Aufmerksamkeit";
    group.append(heading);
    for (const item of visible) {
      const card = document.createElement("article");
      card.className = "royal-announcement" + (item.read ? "" : " is-unread");
      const title = document.createElement("strong"), body = document.createElement("p");
      title.textContent = item.label; body.textContent = item.message;
      card.append(title, body);
      if (!item.read) {
        const actions = document.createElement("div"), button = document.createElement("button");
        actions.className = "royal-announcement-actions";
        button.type = "button"; button.textContent = "Als gelesen";
        button.addEventListener("click", async () => { button.disabled = true; await read(item); if (button.isConnected) button.disabled = false; });
        actions.append(button); card.append(actions);
      }
      group.append(card);
    }
    list.prepend(group);
  }
  return {
    render, reload,
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
