import { api } from "../../core/api.js";

/** Separately owned, opt-in official messages; never merge into watchlist data. */
export function createAnnouncementInbox(root, { onChange, getFilter, isOpen, client = api }) {
  let items = [];
  let enabled = true;
  let timer = null;
  let controller = null;
  let mounted = false;
  let reading = "";
  const settingsChanged = () => { void reload(); };

  async function reload() {
    if (!mounted) return;
    controller?.abort();
    const current = controller = new AbortController();
    try {
      const response = await client.get("/api/announcements", { signal: current.signal });
      if (!mounted || current !== controller) return;
      enabled = response.enabled !== false;
      items = Array.isArray(response.items) ? response.items.slice(0, 75) : [];
      onChange();
    } catch (error) {
      if (current.signal.aborted) return;
      // Keep verified, previously loaded messages through transient outages.
      console.warn("Royal Announcements konnten nicht aktualisiert werden:", error);
    }
  }

  async function read(item) {
    if (reading) return;
    reading = item.id;
    try {
      await client.post("/api/announcements/" + encodeURIComponent(item.id) + "/read", {});
      items = items.map(entry => entry.id === item.id ? { ...entry, read: true } : entry);
      onChange();
    } catch (error) {
      console.warn("Ankündigung konnte nicht bestätigt werden:", error);
    } finally {
      reading = "";
    }
  }

  function render() {
    if (!mounted) return;
    root.querySelector(".royal-announcement-group")?.remove();
    const visible = enabled ? items.filter(item => !item.revoked) : [];
    const unread = visible.filter(item => !item.read).length;
    const badge = root.querySelector("#notif-badge");
    if (!badge) return;
    const total = (Number(badge.textContent) || 0) + unread;
    for (const [filter, addition] of [["all", visible.length], ["new", unread]]) {
      const count = root.querySelector('[data-notif-filter="' + filter + '"] .notif-filter-count');
      if (count) count.textContent = String((Number(count.textContent) || 0) + addition);
    }
    const summary = root.querySelector("#notif-summary");
    if (summary && visible.length) summary.textContent += " · " + visible.length + " Royal-Mitteilungen";
    badge.textContent = String(total);
    badge.classList.toggle("hidden", total === 0);
    root.querySelector("#notif-bell")?.classList.toggle("is-active", total > 0);
    if (unread) {
      const label = total + (total === 1 ? " Hinweis" : " Hinweise");
      const trigger = root.querySelector("#notif-trigger-label");
      if (trigger) trigger.textContent = label;
      root.querySelector("#notif-bell")?.setAttribute("aria-label", "Abo-Inbox öffnen: " + label);
      document.querySelectorAll("[data-notif-mobile-summary]").forEach(node => { node.textContent = label; });
    }
    document.querySelectorAll("[data-notif-mobile-badge]").forEach(node => {
      node.textContent = String(total);
      node.classList.toggle("hidden", total === 0);
    });
    if (!isOpen() || !["all", "new"].includes(getFilter())) return;
    const list = root.querySelector("#notif-list");
    if (!list || !visible.length) return;
    const subset = getFilter() === "new" ? visible.filter(entry => !entry.read) : visible;
    if (!subset.length) return;
    list.querySelector(".notif-empty")?.remove();
    const group = document.createElement("section");
    group.className = "royal-announcement-group";
    const heading = document.createElement("h3");
    heading.className = "royal-announcement-heading";
    heading.textContent = "Offizielle Royal-Mitteilungen";
    group.append(heading);
    subset.forEach(item => {
      const card = document.createElement("article");
      card.className = "royal-announcement" + (item.read ? "" : " is-unread");
      const eyebrow = document.createElement("small");
      eyebrow.textContent = item.category === "event" ? "ROYAL EVENT" : item.category === "important" ? "WICHTIG" : "ROYAL NEWS";
      const title = document.createElement("strong");
      title.textContent = item.title;
      const description = document.createElement("p");
      description.textContent = item.body;
      card.append(eyebrow, title, description);
      const footer = document.createElement("div");
      footer.className = "royal-announcement-actions";
      const date = document.createElement("time");
      date.dateTime = new Date(item.created_at * 1000).toISOString();
      date.textContent = new Date(item.created_at * 1000).toLocaleDateString("de-DE");
      footer.append(date);
      if (!item.read) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = reading === item.id ? "Speichern …" : "Als gelesen";
        button.disabled = Boolean(reading);
        button.addEventListener("click", async () => {
          button.disabled = true;
          await read(item);
          if (button.isConnected) button.disabled = false;
        });
        footer.append(button);
      }
      card.append(footer);
      group.append(card);
    });
    list.prepend(group);
  }

  return {
    render, reload,
    mount() {
      if (mounted) return;
      mounted = true;
      document.addEventListener("royal-announcements-setting-changed", settingsChanged);
      void reload();
      timer = setInterval(() => void reload(), 5 * 60 * 1000);
    },
    unmount() {
      mounted = false;
      document.removeEventListener("royal-announcements-setting-changed", settingsChanged);
      if (timer) clearInterval(timer);
      timer = null;
      controller?.abort();
      controller = null;
      items = [];
    },
  };
}
