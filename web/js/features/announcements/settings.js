import { api } from "../../core/api.js";

/** Settings card is public UI; publisher controls are only returned to the one official owner. */
export function createAnnouncementSettings(root, client = api) {
  let mounted = false, panel = null, admin = null, abort = null;

  const element = (tag, className = "", text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };

  const feedback = (node, message, error = false) => {
    if (!mounted) return;
    node.textContent = message;
    node.classList.toggle("is-error", error);
  };

  async function loadMessages() {
    if (!mounted || !admin) return;
    const list = admin.querySelector(".royal-admin-list");
    try {
      const response = await client.get("/api/announcements/admin/messages");
      if (!mounted) return;
      list.replaceChildren();
      const messages = Array.isArray(response.items) ? response.items : [];
      if (!messages.length) list.append(element("p", "dim", "Noch keine Ankündigungen veröffentlicht."));
      for (const item of messages) {
        const row = element("div", "royal-admin-item");
        row.append(element("strong", "", item.title));
        const stats = item.stats || {};
        row.append(element("small", "", (stats.installations || 0) + " Installationen · "
          + (stats.delivered_profiles || 0) + " Profile empfangen · "
          + (stats.read_profiles || 0) + " Profile gelesen"
          + (item.revoked ? " · Zurückgezogen" : "")));
        if (!item.revoked) {
          const revoke = element("button", "btn btn-ghost", "Zurückziehen");
          revoke.type = "button";
          revoke.addEventListener("click", async () => {
            if (!window.confirm("Diese Ankündigung auf allen Clients zurückziehen?")) return;
            revoke.disabled = true;
            try {
              await client.post("/api/announcements/admin/messages/" + encodeURIComponent(item.id) + "/revoke", {});
              await loadMessages();
            } catch (error) {
              feedback(admin.querySelector(".royal-admin-feedback"), error.message || "Zurückziehen fehlgeschlagen", true);
              revoke.disabled = false;
            }
          });
          row.append(revoke);
        }
        list.append(row);
      }
    } catch (error) {
      feedback(admin.querySelector(".royal-admin-feedback"), error.message || "Statistik derzeit nicht verfügbar", true);
    }
  }

  function createPublisherUI(container) {
    admin = element("section", "settings-group settings-card settings-card-wide royal-admin");
    admin.append(element("h3", "", "Royal Announcements · Betreiberzentrale"));
    admin.append(element("p", "dim settings-hint", "Nur auf dem offiziellen RoyalDownloader-Server für dein Betreiberkonto verfügbar."));
    const title = element("input");
    title.placeholder = "Titel der Ankündigung";
    title.type = "text";
    title.maxLength = 120;
    title.required = true;
    title.className = "royal-admin-title";
    title.setAttribute("aria-label", "Ankündigungstitel");
    const body = element("textarea");
    body.placeholder = "Nachricht an alle RoyalDownloader-Nutzer";
    body.maxLength = 3000;
    body.rows = 5;
    body.required = true;
    body.setAttribute("aria-label", "Ankündigungstext");
    const category = element("select");
    category.setAttribute("aria-label", "Kategorie");
    [["news", "Neuigkeit"], ["event", "Event"], ["important", "Wichtiger Hinweis"]].forEach(([value, label]) => {
      const option = element("option", "", label);
      option.value = value;
      category.append(option);
    });
    const expire = element("input");
    expire.type = "datetime-local";
    expire.setAttribute("aria-label", "Optionales Ablaufdatum");
    const send = element("button", "btn btn-accent", "An alle veröffentlichen");
    send.type = "button";
    const status = element("p", "royal-admin-feedback");
    send.addEventListener("click", async () => {
      if (!title.value.trim() || !body.value.trim()) {
        feedback(status, "Bitte Titel und Nachricht ausfüllen.", true);
        return;
      }
      send.disabled = true;
      feedback(status, "Ankündigung wird signiert und veröffentlicht …");
      try {
        const expires_at = expire.value ? Math.floor(new Date(expire.value).getTime() / 1000) : 0;
        await client.post("/api/announcements/admin/messages", {
          title: title.value.trim(), body: body.value.trim(), category: category.value, expires_at,
        });
        title.value = "";
        body.value = "";
        expire.value = "";
        feedback(status, "Die signierte Ankündigung wurde veröffentlicht.");
        await loadMessages();
      } catch (error) {
        feedback(status, error.message || "Veröffentlichung fehlgeschlagen", true);
      } finally {
        send.disabled = false;
      }
    });
    admin.append(title, body, category, expire, send, status);
    admin.append(element("h4", "", "Veröffentlichungen und Lesestatistik"));
    admin.append(element("div", "royal-admin-list"));
    container.append(admin);
    void loadMessages();
  }

  async function initialize() {
    if (!mounted || !panel) return;
    const current = abort = new AbortController();
    try {
      const [settings, adminStatus] = await Promise.all([
        client.get("/api/announcements/settings", { signal: current.signal }),
        client.get("/api/announcements/admin/status", { signal: current.signal }),
      ]);
      if (!mounted || abort !== current) return;
      const toggle = panel.querySelector("input");
      toggle.checked = settings.enabled !== false;
      if (adminStatus.can_publish && !admin) {
        const container = root.querySelector("#settings-general .settings-card-grid");
        if (container) createPublisherUI(container);
      }
    } catch (error) {
      if (current.signal.aborted || !mounted) return;
      feedback(panel.querySelector(".royal-announcement-setting-status"), "Einstellungen konnten nicht geladen werden.", true);
    }
  }

  return {
    initialize,
    mount() {
      if (mounted) return;
      const container = root.querySelector("#settings-general .settings-card-grid");
      if (!container) return;
      mounted = true;
      panel = element("section", "settings-group settings-card royal-announcement-settings");
      panel.append(element("h3", "", "Offizielle Ankündigungen"));
      panel.append(element("p", "dim settings-hint", "Neuigkeiten und Events des Royal-Teams in der Abo-Inbox empfangen."));
      const label = element("label", "royal-announcement-toggle");
      const input = element("input");
      input.type = "checkbox";
      input.checked = true;
      label.append(input, element("span", "", "Ankündigungen empfangen"));
      const status = element("p", "royal-announcement-setting-status");
      input.addEventListener("change", async () => {
        input.disabled = true;
        try {
          const response = await client.post("/api/announcements/settings", { enabled: input.checked });
          feedback(status, response.enabled ? "Empfang aktiviert." : "Empfang deaktiviert.");
          document.dispatchEvent(new Event("royal-announcements-setting-changed"));
        } catch (error) {
          input.checked = !input.checked;
          feedback(status, "Speichern fehlgeschlagen: " + (error.message || error), true);
        } finally {
          input.disabled = false;
        }
      });
      panel.append(label, status);
      container.append(panel);
      void initialize();
    },
    unmount() {
      mounted = false;
      abort?.abort();
      abort = null;
      panel?.remove();
      admin?.remove();
      panel = null;
      admin = null;
    },
  };
}
