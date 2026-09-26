import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

const HOME_DISCOVERY_PROFILE_KEY = "royal-discovery-profile-v1";

export function createTasteProfile(documentRef, {
  getUser, currentTasteTarget, renderTasteProfileSummary, shouldRenderHome, renderHome,
  homeMovieEntry, homeSeriesEntry, homeEntryMedia, homeEntryKey, onReset,
  storage = null, client = api,
}) {
  let scope = createScope(), bound = false, resetting = false;
  function discoveryProfileStorageKey() {
    const userId = String(getUser()?.id || "");
    return userId && userId !== "admin-legacy" ? `${HOME_DISCOVERY_PROFILE_KEY}:${userId}` : HOME_DISCOVERY_PROFILE_KEY;
  }
  async function sendEvent(event, { acceptProfile = false } = {}) {
    if (!scope.active) return;
    const owner = scope, key = discoveryProfileStorageKey();
    try {
      const response = await client.post("/api/taste/events", event, { signal: owner.signal });
      if (owner.active && key === discoveryProfileStorageKey() && acceptProfile && response?.profile) applyServerTasteProfile(response.profile);
    } catch (error) {
      if (owner.active && key === discoveryProfileStorageKey()) console.warn("Geschmackssignal konnte nicht gespeichert werden:", error);
    }
  }
  async function reset() {
    if (!scope.active || resetting || !documentRef.defaultView.confirm("Geschmacksprofil wirklich vollständig zurücksetzen?")) return;
    const owner = scope, key = discoveryProfileStorageKey();
    resetting = true;
    try {
      const response = await client.post("/api/taste/reset", undefined, { signal: owner.signal });
      if (!owner.active || key !== discoveryProfileStorageKey()) return;
      applyServerTasteProfile(response.profile); renderHome(); onReset(response.user);
    } catch (error) {
      if (owner.active && key === discoveryProfileStorageKey()) documentRef.defaultView.alert(`Profil konnte nicht zurückgesetzt werden: ${error.message}`);
    } finally { resetting = false; }
  }
  function loadDiscoveryProfile() {
    let profile = null;
    try {
      profile = JSON.parse((storage || documentRef.defaultView.localStorage).getItem(discoveryProfileStorageKey()) || "null");
    } catch {
      profile = null;
    }
    if (!profile || typeof profile !== "object") {
      profile = { genres: {}, kinds: {}, dimensions: {}, recent: [], blocked_items: [], item_feedback: {}, interactions: 0, updatedAt: Date.now() };
    }
    profile.genres = profile.genres && typeof profile.genres === "object" ? profile.genres : {};
    profile.kinds = profile.kinds && typeof profile.kinds === "object" ? profile.kinds : {};
    profile.dimensions = profile.dimensions && typeof profile.dimensions === "object" ? profile.dimensions : {};
    profile.blocked_items = Array.isArray(profile.blocked_items) ? profile.blocked_items : [];
    profile.item_feedback = profile.item_feedback && typeof profile.item_feedback === "object" ? profile.item_feedback : {};
    profile.recent = Array.isArray(profile.recent) ? profile.recent.slice(0, 60) : [];
    profile.interactions = Number(profile.interactions || 0);
    const elapsedDays = Math.floor((Date.now() - Number(profile.updatedAt || Date.now())) / 86400000);
    if (elapsedDays > 0 && !Object.keys(profile.dimensions).length) {
      const factor = Math.pow(0.985, Math.min(elapsedDays, 120));
      Object.keys(profile.genres).forEach((genre) => {
        profile.genres[genre] = Number(profile.genres[genre] || 0) * factor;
      });
      Object.keys(profile.kinds).forEach((kind) => {
        profile.kinds[kind] = Number(profile.kinds[kind] || 0) * factor;
      });
      profile.updatedAt = Date.now();
      saveDiscoveryProfile(profile);
    }
    return profile;
  }

  function saveDiscoveryProfile(profile) {
    try {
      (storage || documentRef.defaultView.localStorage).setItem(discoveryProfileStorageKey(), JSON.stringify(profile));
    } catch {
      // Private Modi können lokalen Speicher blockieren; Entdecken bleibt nutzbar.
    }
  }

  function applyServerTasteProfile(serverProfile) {
    if (!serverProfile || typeof serverProfile !== "object") return loadDiscoveryProfile();
    const profile = {
      ...serverProfile,
      genres: serverProfile.genres || serverProfile.dimensions?.genres || {},
      kinds: serverProfile.kinds || serverProfile.dimensions?.media_types || {},
      dimensions: serverProfile.dimensions || {},
      recent: Array.isArray(serverProfile.recent) ? serverProfile.recent : [],
      blocked_items: Array.isArray(serverProfile.blocked_items) ? serverProfile.blocked_items : [],
      item_feedback: serverProfile.item_feedback || {},
      interactions: Number(serverProfile.interactions || 0),
      updatedAt: Number(serverProfile.updated_at || 0) * 1000 || Date.now(),
    };
    saveDiscoveryProfile(profile);
    renderTasteProfileSummary(profile);
    updateTasteFeedbackButtons();
    return profile;
  }

  async function syncTasteProfile() {
    if (!scope.active) return;
    const owner = scope;
    const key = discoveryProfileStorageKey();
    const current = () => owner.active && key === discoveryProfileStorageKey();
    const localProfile = loadDiscoveryProfile();
    try {
      let serverProfile = await client.get("/api/taste/profile", { signal: owner.signal });
      if (!current()) return;
      if (!serverProfile.legacy_imported && localProfile.interactions > 0) {
        const imported = await client.post("/api/taste/import", {
          genres: localProfile.genres || {},
          kinds: localProfile.kinds || {},
        }, { signal: owner.signal });
        if (!current()) return;
        serverProfile = imported.profile || serverProfile;
      }
      applyServerTasteProfile(serverProfile);
      if (shouldRenderHome()) renderHome();
    } catch (error) {
      if (!current()) return;
      console.warn("Geschmacksprofil konnte nicht synchronisiert werden:", error);
      renderTasteProfileSummary(localProfile, true);
    }
  }

  function tasteMetadata(kind, item = {}) {
    const cast = (item.cast || []).map((person) => typeof person === "string" ? person : person?.name).filter(Boolean);
    return {
      genres: item.genres || [],
      tags: item.keywords || item.tags || [],
      studios: item.production_companies || item.studios || [],
      directors: item.directors || [],
      actors: cast,
      languages: item.spoken_languages || item.languages || item.content_language || [],
      year: item.year || item.release_date || "",
      runtime: item.runtime || "",
      media_type: kind,
    };
  }

  const pendingTasteFeedbackKeys = new Set();
  function applyLocalTasteFeedback(itemKey, action) {
    const profile = loadDiscoveryProfile();
    profile.item_feedback = { ...profile.item_feedback };
    const blockedItems = new Set(profile.blocked_items || []);
    if (action === "clear") {
      delete profile.item_feedback[itemKey]; blockedItems.delete(itemKey);
    } else {
      profile.item_feedback[itemKey] = action;
      if (["dislike", "dismiss"].includes(action)) blockedItems.add(itemKey); else blockedItems.delete(itemKey);
    }
    profile.blocked_items = [...blockedItems]; profile.updatedAt = Date.now();
    saveDiscoveryProfile(profile); updateTasteFeedbackButtons();
  }
  function updateTasteFeedbackButtons() {
    const profile = loadDiscoveryProfile();
    for (const [kind, prefix] of [["movie", "fp"], ["series", "series"]]) {
      const target = currentTasteTarget(kind);
      const action = target ? profile.item_feedback?.[target.key] : "";
      const like = documentRef.getElementById(`${prefix}-taste-like`);
      const dislike = documentRef.getElementById(`${prefix}-taste-dislike`);
      if (!like || !dislike) continue;
      const pending = Boolean(target && pendingTasteFeedbackKeys.has(target.key));
      like.disabled = !target; dislike.disabled = !target;
      like.closest(".taste-feedback")?.classList.toggle("is-saving", pending);
      like.closest(".taste-feedback")?.setAttribute("aria-busy", String(pending));
      const liked = action === "like" || action === "favorite";
      const disliked = action === "dislike" || action === "dismiss";
      like.setAttribute("aria-pressed", String(liked));
      dislike.setAttribute("aria-pressed", String(disliked));
      like.setAttribute("aria-label", liked ? "Bewertung Mehr davon entfernen" : "Mehr davon empfehlen");
      dislike.setAttribute("aria-label", disliked ? "Bewertung Nicht für mich entfernen" : "Nicht für mich markieren");
      like.title = liked ? "Bewertung entfernen" : "Ähnliche Inhalte stärker empfehlen";
      dislike.title = disliked ? "Bewertung entfernen" : "Ähnliche Inhalte seltener empfehlen";
      like.querySelector(".taste-icon").textContent = liked ? "♥" : "♡";
      dislike.querySelector(".taste-icon").textContent = disliked ? "⊗" : "⊘";
    }
  }
  async function setTasteFeedback(kind, requestedAction) {
    if (!scope.active) return;
    const owner = scope;
    const key = discoveryProfileStorageKey();
    const current = () => owner.active && key === discoveryProfileStorageKey();
    const target = currentTasteTarget(kind);
    if (!target || pendingTasteFeedbackKeys.has(target.key)) return;
    const previousProfile = loadDiscoveryProfile();
    const currentAction = previousProfile.item_feedback?.[target.key] || "";
    const wasBlocked = previousProfile.blocked_items.includes(target.key);
    const sameChoice = requestedAction === "like"
      ? ["like", "favorite"].includes(currentAction)
      : ["dislike", "dismiss"].includes(currentAction);
    const action = sameChoice ? "clear" : requestedAction;
    pendingTasteFeedbackKeys.add(target.key); applyLocalTasteFeedback(target.key, action);
    try {
      const response = await client.post("/api/taste/feedback", {
        item_key: target.key,
        action,
        source: "web",
        media_type: kind,
        title: target.item.title || "",
        metadata: tasteMetadata(kind, target.item),
      }, { signal: owner.signal });
      if (!current()) return;
      applyServerTasteProfile(response.profile);
      renderHome();
    } catch (error) {
      if (!current()) return;
      const rollbackProfile = loadDiscoveryProfile();
      rollbackProfile.item_feedback = { ...rollbackProfile.item_feedback };
      if (currentAction) rollbackProfile.item_feedback[target.key] = currentAction; else delete rollbackProfile.item_feedback[target.key];
      const blockedItems = new Set(rollbackProfile.blocked_items || []);
      if (wasBlocked) blockedItems.add(target.key); else blockedItems.delete(target.key);
      rollbackProfile.blocked_items = [...blockedItems];
      saveDiscoveryProfile(rollbackProfile);
      console.warn("Bewertung konnte nicht gespeichert werden:", error);
    } finally {
      pendingTasteFeedbackKeys.delete(target.key);
      if (current()) updateTasteFeedbackButtons();
    }
  }

  function trackDiscoveryPreference(kind, item, weight = 1, action = "open") {
    if (!scope.active) return;
    if (!item) return;
    const entry = kind === "movie" ? homeMovieEntry(item) : homeSeriesEntry(item);
    const media = kind === "anime" ? item : homeEntryMedia(entry);
    const key = kind === "anime"
      ? `anime:${item.id || item.base_slug || item.slug || "unknown"}`
      : homeEntryKey(entry);
    const profile = loadDiscoveryProfile();
    const cleanGenres = [...new Set((media.genres || [])
      .map((genre) => String(genre || "").trim())
      .filter(Boolean))].slice(0, 5);
    for (const genre of cleanGenres) {
      profile.genres[genre] = Math.min(80, Number(profile.genres[genre] || 0) + weight);
    }
    profile.kinds[kind] = Math.min(80, Number(profile.kinds[kind] || 0) + weight * 0.45);
    profile.recent = [
      { key, action, at: Date.now() },
      ...profile.recent.filter((event) => event?.key !== key),
    ].slice(0, 60);
    profile.interactions += 1;
    profile.updatedAt = Date.now();
    saveDiscoveryProfile(profile);
    void sendEvent({
      action,
      source: "web",
      media_type: kind,
      item_key: key,
      title: item.title || "",
      metadata: tasteMetadata(kind, media),
    }, { acceptProfile: true });
  }

  return {
    key: discoveryProfileStorageKey, load: loadDiscoveryProfile, save: saveDiscoveryProfile,
    accept: applyServerTasteProfile, sync: syncTasteProfile, metadata: tasteMetadata,
    updateButtons: updateTasteFeedbackButtons, feedback: setTasteFeedback, track: trackDiscoveryPreference,
    event: sendEvent,
    mount() {
      if (bound) return;
      if (!scope.active) scope = createScope();
      bound = true;
      for (const [kind, prefix] of [["movie", "fp"], ["series", "series"]]) {
        for (const action of ["like", "dislike"]) scope.listen(documentRef.getElementById(`${prefix}-taste-${action}`), "click", () => { void setTasteFeedback(kind, action); });
      }
      scope.listen(documentRef.getElementById("taste-profile-reset"), "click", () => { void reset(); });
    },
    unmount() { scope.dispose(); bound = false; pendingTasteFeedbackKeys.clear(); },
  };
}
