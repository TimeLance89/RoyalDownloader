import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

// Stable UI identity, not an authentication/signature hash. Works on local HTTP.
export function inboxKey(kind, value) {
  const text = JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
  const hash = [2166136261, 2246822519, 3266489917, 668265263];
  for (let i = 0; i < text.length; i++) for (let j = 0; j < hash.length; j++) hash[j] = Math.imul(hash[j] ^ text.charCodeAt(i), 16777619 + j * 2);
  return kind + ":" + hash.map(value => (value >>> 0).toString(16).padStart(8, "0")).join("");
}

export function subscriptionKey(entry) {
  const fields = ["base_slug", "open_count", "new_count", "queued_count", "downloaded_count", "failed_count", "status", "last_error", "cleanup_last_error", "waiting_language_count", "language_pending_count", "upcoming_count", "waiting_release_count", "last_unread_downloaded_episode", "last_downloaded_episode", "episode_states", "inbox_episode_revision"];
  return inboxKey("subscription", fields.map(key => entry[key] ?? null));
}

export function createInboxDismissals({ getUser, onChange, client = api }) {
  let scope, owner = "", keys = new Set();
  const valid = current => current?.active && owner && owner === String(getUser()?.id || "");
  return {
    has: key => owner === String(getUser()?.id || "") && keys.has(key),
    async reload() {
      const current = scope;
      if (!valid(current)) return;
      const data = await client.get("/api/inbox/dismissals", { signal: current.signal, headers: { "X-Royal-Profile": owner } });
      if (!valid(current)) return;
      keys = new Set([...keys, ...(Array.isArray(data.keys) ? data.keys : [])]); onChange();
    },
    async remove(values) {
      const current = scope;
      if (!valid(current)) throw new Error("Profil hat sich geändert. Bitte neu laden.");
      const unique = [...new Set(values)].filter(key => !keys.has(key));
      for (let i = 0; i < unique.length; i += 500) {
        const batch = unique.slice(i, i + 500);
        await client.post("/api/inbox/dismissals", { keys: batch }, { signal: current.signal, headers: { "X-Royal-Profile": owner } });
        if (!valid(current)) return;
        batch.forEach(key => keys.add(key)); onChange();
      }
    },
    mount() { if (scope) return; scope = createScope(); owner = String(getUser()?.id || ""); keys = new Set(); },
    unmount() { scope?.dispose(); scope = null; owner = ""; keys.clear(); },
  };
}
