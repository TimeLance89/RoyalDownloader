/* Royal Daily Top 10 v2: stable, explainable cross-source popularity ranking. */
(() => {
  "use strict";

  if (window.__royalDailyTopV2Installed) return;
  window.__royalDailyTopV2Installed = true;

  const DAILY_TOP_STORAGE_KEY = "royal-home-daily-top-v2";
  const DAILY_TOP_LIMIT = 10;
  const legacyHomeTopEntries = window.homeTopEntries;
  const baseCreateHomeCard = window.createHomeCard;

  let response = null;
  let loading = false;
  let loadedPeriod = "";

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
      const parsed = JSON.parse(localStorage.getItem(DAILY_TOP_STORAGE_KEY) || "null");
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch {
      return null;
    }
  }

  function saveSnapshot(snapshot) {
    try {
      localStorage.setItem(DAILY_TOP_STORAGE_KEY, JSON.stringify(snapshot));
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
    return {
      identity: candidate.identity,
      kind: candidate.kind,
      item: candidate.item,
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
      .filter((candidate) => candidate?.identity && candidate?.item && !isBlocked(candidate));
    const incomingByIdentity = new Map(incoming.map((candidate) => [candidate.identity, candidate]));
    const stored = loadSnapshot();

    if (stored?.version === 2 && stored.period === period && Array.isArray(stored.current)) {
      const current = stored.current.filter((candidate) => candidate?.identity && !isBlocked(candidate));
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

    const previous = stored?.version === 2
      && stored.period === previousDayKey(period)
      && Array.isArray(stored.current)
      ? stored.current
      : [];
    const current = incoming.slice(0, DAILY_TOP_LIMIT).map(candidateSnapshot);
    const next = { version: 2, period, previous, current };
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
    if (stored?.version === 2 && stored.period === period) {
      const entries = entriesFromSnapshot(stored);
      if (entries.length) return entries;
    }
    return typeof legacyHomeTopEntries === "function" ? legacyHomeTopEntries() : [];
  }

  function movementTitle(dailyTop) {
    const movement = dailyTop?.movement || {};
    if (movement.direction === "new") return "Neu in den heutigen Top 10";
    if (movement.direction === "up") return `${movement.delta} Platz/Plätze gestiegen`;
    if (movement.direction === "down") return `${Math.abs(movement.delta)} Platz/Plätze gefallen`;
    return "Position seit gestern unverändert";
  }

  function enhanceRankedCard(card, entry, requestedRank) {
    const dailyTop = entry?.item?.daily_top;
    if (!card || !requestedRank || !dailyTop) return card;
    const globalRank = Number(dailyTop.global_rank || requestedRank);
    const rank = card.querySelector(".home-card-rank");
    if (rank) rank.textContent = String(globalRank);
    const currentLabel = card.getAttribute("aria-label") || "";
    card.setAttribute("aria-label", currentLabel.replace(/^Platz \d+:/, `Platz ${globalRank}:`));
    card.dataset.dailyTopScore = Number(dailyTop.score || 0).toFixed(2);
    card.dataset.dailyTopGlobalRank = String(globalRank);

    const overlay = card.querySelector(".home-card-overlay");
    const meta = overlay?.querySelector("span");
    if (overlay && !overlay.querySelector(".daily-top-movement")) {
      const movement = document.createElement("span");
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
    const title = document.getElementById("home-top-title");
    const eyebrow = title?.closest(".home-rail-head")?.querySelector(".home-rail-eyebrow");
    if (title) title.textContent = "Top 10";
    if (eyebrow) eyebrow.textContent = "Heute über deine Quellen hinweg angesagt";
    const track = document.getElementById("home-top-track");
    if (track) track.setAttribute("aria-label", "Tägliche Top 10 nach Popularität");
  }

  function installStyle() {
    if (document.getElementById("daily-top-v2-style")) return;
    const style = document.createElement("style");
    style.id = "daily-top-v2-style";
    style.textContent = `
      .home-card.is-ranked .daily-top-movement{
        align-self:flex-start;display:inline-flex;align-items:center;justify-content:center;
        min-width:34px;height:20px;padding:0 7px;margin:2px 0 4px;border-radius:999px;
        border:1px solid rgba(255,255,255,.16);background:rgba(8,11,19,.72);
        color:#c7cfdf;font-size:10px;font-weight:800;letter-spacing:.04em;line-height:1;
        backdrop-filter:blur(8px);box-shadow:0 4px 14px rgba(0,0,0,.18)
      }
      .home-card.is-ranked .daily-top-movement.is-up{color:#8fe5b1;border-color:rgba(93,211,139,.28)}
      .home-card.is-ranked .daily-top-movement.is-down{color:#e4a3a9;border-color:rgba(224,112,126,.25)}
      .home-card.is-ranked .daily-top-movement.is-new{color:#f2d68b;border-color:rgba(225,184,75,.3)}
      .home-card.is-ranked .daily-top-movement.is-flat{color:#aeb7c9}
    `;
    document.head.appendChild(style);
  }

  async function refreshDailyTop(forceRender = true) {
    const period = dayKey();
    if (loading || (loadedPeriod === period && response)) return;
    loading = true;
    try {
      const payload = await api.get("/api/daily-top?" + new URLSearchParams({ period }));
      if (payload?.version !== 2 || !Array.isArray(payload.candidates)) return;
      response = payload;
      loadedPeriod = period;
      reconcileSnapshot(payload);
      updateHeading();
      if (forceRender && state.tab === "home" && typeof renderHome === "function") renderHome();
    } catch (error) {
      console.warn("Daily Top 10 konnte nicht aktualisiert werden:", error);
    } finally {
      loading = false;
    }
  }

  window.homeTopEntries = dailyTopEntries;
  if (typeof baseCreateHomeCard === "function") {
    window.createHomeCard = function dailyTopV2HomeCard(entry, rank = 0, ...args) {
      const card = baseCreateHomeCard(entry, rank, ...args);
      return enhanceRankedCard(card, entry, rank);
    };
  }

  installStyle();
  updateHeading();
  void refreshDailyTop(true);

  function refreshAtDayBoundary() {
    if (loadedPeriod === dayKey()) return;
    response = null;
    loadedPeriod = "";
    void refreshDailyTop(true);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshAtDayBoundary();
  });
  window.setInterval(refreshAtDayBoundary, 5 * 60 * 1000);
})();
