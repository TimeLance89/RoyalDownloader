import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Personal state belongs to one open detail and survives its content updates. */
export function createSavedMediaAction(button, note, { client = api } = {}) {
  let scope = null, activeKey = null, activeMedia = null;
  function close() { scope?.dispose(); scope = null; activeKey = null; activeMedia = null; }
  function show(media, mediaType) {
    const identity = Number(media?.tmdb_id);
    const validIdentity = Number.isSafeInteger(identity) && identity > 0;
    const key = validIdentity ? `${mediaType}:${identity}` : null;
    if (key && key === activeKey && scope?.active) {
      activeMedia = media;
      return;
    }
    close();
    if (!button || !note) return;
    const current = createScope(); scope = current;
    activeKey = key; activeMedia = media;
    let saved = false, loaded = false, busy = false, reading = false, revision = 0;
    button.disabled = true; button.textContent = "+ Merken";
    button.setAttribute("aria-pressed", "false");
    note.textContent = "";
    if (!validIdentity) {
      note.textContent = "Vormerken ist möglich, sobald der Titel eindeutig zugeordnet ist.";
      return;
    }
    function render(payload) {
      saved = payload.items.some(item => item.media_type === mediaType && item.tmdb_id === identity);
      loaded = true; button.disabled = busy;
      button.textContent = saved ? "Gemerkt ✓" : "+ Merken";
      button.setAttribute("aria-pressed", String(saved));
      button.title = saved ? "Aus deiner RD-Merkliste entfernen" : "Für dein verknüpftes Jellyfin-Profil merken";
      if (!saved) note.textContent = "";
      else if (payload.sync.state === "unlinked") note.textContent = "In RD gemerkt · Jellyfin-Profil im Profilbereich verknüpfen.";
      else if (payload.sync.state === "unconfigured") note.textContent = "In RD gemerkt · Jellyfin ist noch nicht eingerichtet.";
      else if (payload.sync.state === "error") note.textContent = "In RD gemerkt · Jellyfin-Abgleich wird erneut versucht.";
      else if (payload.sync.ready.includes(`${mediaType}:${identity}`)) note.textContent = "In deiner Jellyfin-Merkliste verfügbar.";
      else note.textContent = "Gemerkt · erscheint in Jellyfin, sobald verfügbar.";
    }
    async function refresh() {
      if (busy || reading || !current.active) return;
      reading = true;
      const readRevision = revision;
      try {
        const payload = await client.get("/api/me/saved-media", { signal: current.signal });
        if (current.active && !busy && readRevision === revision) render(payload);
      } catch (error) {
        if (!current.active || error.name === "AbortError") return;
        note.textContent = loaded ? "Vormerkungsstatus konnte nicht aktualisiert werden." : "Vormerkungen konnten nicht geladen werden · erneuter Versuch folgt.";
      } finally {
        reading = false;
      }
    }
    current.listen(button, "click", async () => {
      if (!loaded || busy) return;
      revision += 1;
      busy = true; button.disabled = true;
      try {
        const payload = await client.post("/api/me/saved-media", {
          media_type: mediaType, tmdb_id: identity, title: String(activeMedia?.title || "Titel").slice(0, 240), saved: !saved,
        }, { signal: current.signal });
        if (current.active) render(payload);
      } catch (error) {
        if (current.active && error.name !== "AbortError") note.textContent = `Vormerkung nicht geändert: ${error.message}`;
      } finally {
        busy = false;
        if (current.active) button.disabled = false;
      }
    });
    current.interval(() => { void refresh(); }, 15_000);
    void refresh();
  }
  return { show, close };
}
