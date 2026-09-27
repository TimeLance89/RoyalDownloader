import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Stable daily ranking: the backend owns scoring; the browser preserves daily positions. */
export function createDailyTop(root, { fallbackEntries, localDateKey, homeEntryKey,
  discoveryV2LogicalKey, loadDiscoveryProfile, selectFpRow, closeGlobalSearch, loadSeries, renderHome,
  client = api, storage = globalThis.localStorage }) {
  let scope, initialized = false;
  const cardEntries = new WeakMap();
  const DAILY_TOP_STORAGE_KEY = "royal-home-daily-top-v3";
  const DAILY_TOP_STORAGE_VERSION = 3;
  const DAILY_TOP_LIMIT = 10;

  let response = null;
  let loading = false;
  let loadedPeriod = "";

  function cleanTitle(value) {
    let title = String(value || "").trim();
    let previous = "";
    while (title && title !== previous) {
      previous = title;
      title = title
        .replace(/\s*\[[^\]]{1,40}\]\s*$/i, "")
        .replace(/\s*\*(?:subbed|dubbed|ger(?:man)?(?:\s+dub)?|eng(?:lish)?)\*\s*$/i, "")
        .trim();
    }
    return title;
  }

  function isPresentable(candidate) {
    const item = candidate?.item || {};
    return cleanTitle(item.title).length >= 2
      && Boolean(String(item.cover_url || item.backdrop_url || "").trim());
  }

  function dayKey(date = new Date()) {
    if (typeof localDateKey === "function") return localDateKey(date);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function previousDayKey(period) {
    const parsed = new Date(`${period}T12:00:00`);
    if (Number.isNaN(parsed.getTime())) return "";
    parsed.setDate(parsed.getDate() - 1);
    return dayKey(parsed);
  }

  function loadSnapshot() {
    try {
      const parsed = JSON.parse(storage.getItem(DAILY_TOP_STORAGE_KEY) || "null");
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch {
      return null;
    }
  }

  function saveSnapshot(snapshot) {
    try {
      storage.setItem(DAILY_TOP_STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
      // The ranking remains usable in private browser modes without storage.
    }
  }

  function logicalBlockedKeys(candidate) {
    const item = candidate?.item || {};
    const keys = new Set([String(candidate?.identity || "")].filter(Boolean));
    const tmdbId = String(item.tmdb_id || "").trim();
    if (tmdbId) keys.add(`${candidate.kind}:tmdb:${tmdbId}`);
    const entry = { kind: candidate.kind, item };
    if (typeof homeEntryKey === "function") keys.add(homeEntryKey(entry));
    if (typeof discoveryV2LogicalKey === "function") keys.add(discoveryV2LogicalKey(entry));
    return keys;
  }

  function isBlocked(candidate) {
    const profile = typeof loadDiscoveryProfile === "function" ? loadDiscoveryProfile() : {};
    const blocked = new Set(Array.isArray(profile?.blocked_items) ? profile.blocked_items : []);
    return [...logicalBlockedKeys(candidate)].some((key) => key && blocked.has(key));
  }

  function candidateSnapshot(candidate) {
    const item = { ...(candidate.item || {}) };
    item.title = cleanTitle(item.title);
    return {
      identity: candidate.identity,
      kind: candidate.kind,
      item,
      global_rank: Number(candidate.global_rank || 0),
      score: Number(candidate.score || 0),
      components: candidate.components || {},
      provider_ranks: candidate.provider_ranks || {},
      availability_providers: candidate.availability_providers || [],
      tmdb_trend_rank: candidate.tmdb_trend_rank || null,
    };
  }

  function reconcileSnapshot(payload) {
    const period = String(payload?.period || dayKey());
    const incoming = (payload?.candidates || [])
      .filter((candidate) => candidate?.identity && candidate?.item && isPresentable(candidate) && !isBlocked(candidate));
    const incomingByIdentity = new Map(incoming.map((candidate) => [candidate.identity, candidate]));
    const stored = loadSnapshot();

    if (stored?.version === DAILY_TOP_STORAGE_VERSION && stored.period === period && Array.isArray(stored.current)) {
      const current = stored.current.filter((candidate) => candidate?.identity && isPresentable(candidate) && !isBlocked(candidate));
      const used = new Set(current.map((candidate) => candidate.identity));
      for (const candidate of incoming) {
        if (current.length >= DAILY_TOP_LIMIT) break;
        if (used.has(candidate.identity)) continue;
        current.push(candidateSnapshot(candidate));
        used.add(candidate.identity);
      }
      const refreshed = current.slice(0, DAILY_TOP_LIMIT).map((candidate) => {
        const fresh = incomingByIdentity.get(candidate.identity);
        if (!fresh) return candidate;
        return {
          ...candidateSnapshot(fresh),
          // Same-day ranks are immutable. Metadata may refresh, position does not.
          global_rank: Number(candidate.global_rank || fresh.global_rank || 0),
        };
      });
      const next = { ...stored, current: refreshed };
      saveSnapshot(next);
      return next;
    }

    const previous = stored?.version === DAILY_TOP_STORAGE_VERSION
      && stored.period === previousDayKey(period)
      && Array.isArray(stored.current)
      ? stored.current
      : [];
    const current = incoming.slice(0, DAILY_TOP_LIMIT).map(candidateSnapshot);
    const next = { version: DAILY_TOP_STORAGE_VERSION, period, previous, current };
    saveSnapshot(next);
    return next;
  }

  function movementFor(candidate, previous) {
    const old = new Map((previous || []).map((item) => [item.identity, Number(item.global_rank || 0)]));
    const previousRank = old.get(candidate.identity);
    const currentRank = Number(candidate.global_rank || 0);
    if (!previousRank || !currentRank) return { label: "NEW", direction: "new", delta: 0 };
    const delta = previousRank - currentRank;
    if (delta > 0) return { label: `↑${delta}`, direction: "up", delta };
    if (delta < 0) return { label: `↓${Math.abs(delta)}`, direction: "down", delta };
    return { label: "—", direction: "flat", delta: 0 };
  }

  function entriesFromSnapshot(snapshot) {
    if (!snapshot?.current?.length) return [];
    return snapshot.current
      .filter((candidate) => !isBlocked(candidate))
      .slice(0, DAILY_TOP_LIMIT)
      .map((candidate) => {
        const movement = movementFor(candidate, snapshot.previous || []);
        return {
          kind: candidate.kind,
          item: {
            ...(candidate.item || {}),
            daily_top: {
              identity: candidate.identity,
              global_rank: Number(candidate.global_rank || 0),
              score: Number(candidate.score || 0),
              components: candidate.components || {},
              provider_ranks: candidate.provider_ranks || {},
              availability_providers: candidate.availability_providers || [],
              tmdb_trend_rank: candidate.tmdb_trend_rank || null,
              movement,
            },
          },
        };
      });
  }

  function dailyTopEntries() {
    const period = dayKey();
    if (response?.period === period) {
      return entriesFromSnapshot(reconcileSnapshot(response));
    }
    const stored = loadSnapshot();
    if (stored?.version === DAILY_TOP_STORAGE_VERSION && stored.period === period) {
      const entries = entriesFromSnapshot(stored);
      if (entries.length) return entries;
    }
    return typeof fallbackEntries === "function" ? fallbackEntries() : [];
  }

  function movementTitle(dailyTop) {
    const movement = dailyTop?.movement || {};
    if (movement.direction === "new") return "Neu in den heutigen Top 10";
    if (movement.direction === "up") return `${movement.delta} Platz/Plätze gestiegen`;
    if (movement.direction === "down") return `${Math.abs(movement.delta)} Platz/Plätze gefallen`;
    return "Position seit gestern unverändert";
  }

  function openDailyTopEntry(entry) {
    const item = entry?.item || {};
    if (!item.daily_top) return false;
    if (entry.kind === "movie" && item.slug && typeof selectFpRow === "function") {
      if (typeof closeGlobalSearch === "function") closeGlobalSearch();
      selectFpRow(item.slug, item);
      return true;
    }
    if (entry.kind === "series" && item.base_slug && typeof loadSeries === "function") {
      if (typeof closeGlobalSearch === "function") closeGlobalSearch();
      loadSeries(item);
      return true;
    }
    return false;
  }

  function enhanceRankedCard(card, entry, requestedRank) {
    const dailyTop = entry?.item?.daily_top;
    if (card && dailyTop) cardEntries.set(card, entry);
    if (!card || !requestedRank || !dailyTop) return card;
    const visibleRank = Number(requestedRank || dailyTop.global_rank || 0);
    const globalRank = Number(dailyTop.global_rank || visibleRank);
    const rank = card.querySelector(".home-card-rank");
    if (rank) rank.textContent = String(visibleRank);
    const primaryAction = card.querySelector(".home-card-primary-action");
    const currentLabel = primaryAction?.getAttribute("aria-label") || "";
    primaryAction?.setAttribute("aria-label", currentLabel.replace(/^Platz \d+:/, `Platz ${visibleRank}:`));
    card.dataset.dailyTopScore = Number(dailyTop.score || 0).toFixed(2);
    card.dataset.dailyTopGlobalRank = String(globalRank);
    card.dataset.dailyTopDisplayRank = String(visibleRank);

    const overlay = card.querySelector(".home-card-overlay");
    const meta = overlay?.querySelector("span");
    if (overlay && !overlay.querySelector(".daily-top-movement")) {
      const movement = root.ownerDocument.createElement("span");
      movement.className = `daily-top-movement is-${dailyTop.movement?.direction || "flat"}`;
      movement.textContent = dailyTop.movement?.label || "—";
      movement.title = movementTitle(dailyTop);
      movement.setAttribute("aria-label", movement.title);
      if (meta) overlay.insertBefore(movement, meta);
      else overlay.appendChild(movement);
    }
    return card;
  }

  function updateHeading() {
    const title = root.querySelector("#home-top-title");
    const eyebrow = title?.closest(".home-rail-head")?.querySelector(".home-rail-eyebrow");
    if (title) title.textContent = "Top 10";
    if (eyebrow) eyebrow.textContent = "Heute über deine Quellen hinweg angesagt";
    const track = root.querySelector("#home-top-track");
    if (track) track.setAttribute("aria-label", "Tägliche Top 10 nach Popularität");
  }

  async function refreshDailyTop(forceRender = true) {
    const period = dayKey();
    if (!scope?.active || loading || (loadedPeriod === period && response)) return;
    const current = scope;
    loading = true;
    try {
      const payload = await client.get("/api/daily-top?" + new URLSearchParams({ period }), { signal: current.signal });
      if (!current.active) return;
      if (payload?.version !== 2 || !Array.isArray(payload.candidates)) return;
      response = payload;
      loadedPeriod = period;
      reconcileSnapshot(payload);
      updateHeading();
      if (forceRender && current.active) renderHome();
    } catch (error) {
      if (current.active) console.warn("Daily Top 10 konnte nicht aktualisiert werden:", error);
    } finally {
      if (current.active) loading = false;
    }
  }

  function refreshAtDayBoundary() {
    if (loadedPeriod === dayKey()) return;
    response = null; loadedPeriod = ""; void refreshDailyTop(true);
  }
  return {
    entries: dailyTopEntries, enhance: enhanceRankedCard, open: openDailyTopEntry,
    refresh: refreshAtDayBoundary,
    mount() {
      if (scope) return; scope = createScope(); updateHeading();
      scope.listen(root, "click", event => {
        const card = event.target.closest(".home-card"); const entry = cardEntries.get(card);
        if (!entry) return;
        const action = event.target.closest("a, button, [role='button'], [data-card-action]");
        if (action && !action.classList.contains("home-card-primary-action")) return;
        if (openDailyTopEntry(entry)) { event.preventDefault(); event.stopImmediatePropagation(); }
      }, true);
      scope.listen(root.ownerDocument, "visibilitychange", () => { if (!root.ownerDocument.hidden) refreshAtDayBoundary(); });
      // Local midnight has no push event. Only a mounted Home needs the clock check.
      scope.interval(refreshAtDayBoundary, 5 * 60 * 1000);
      if (!initialized) { initialized = true; void refreshDailyTop(false); }
      else refreshAtDayBoundary();
    },
    unmount() { scope?.dispose(); scope = null; loading = false; },
  };
}
