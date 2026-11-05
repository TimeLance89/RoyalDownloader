import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

const MODES = {
  today: "Heute über deine Quellen hinweg angesagt",
  week: "Die letzten sieben Chart-Tage",
  breakouts: "Messbarer Zuwachs seit gestern",
};
const SIGNALS = {
  views_rank: "Aufrufe", trending_rank: "Trending", popularity_rank: "Popularität",
  editorial_top: "Top-Rubrik · reduziert gewichtet", rating_rank: "Bewertung",
  recent_uploads: "Neuheiten", unknown: "Katalog",
};
const CONFIDENCE = { high: "Hoch", medium: "Mittel", limited: "Begrenzt" };
const number = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 });
const dateLabel = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "numeric", timeZone: "UTC" });
const dayKey = () => new Date().toISOString().slice(0, 10);

function movementBadge(movement) {
  const delta = Math.abs(movement?.delta || 0);
  switch (movement?.direction) {
    case "new": return ["NEW", "Erstmals in den Charts erfasst"];
    case "returning": return ["RE", "Wieder in den Charts"];
    case "up": return [`↑ ${delta}`, `${delta} nach oben seit gestern`];
    case "down": return [`↓ ${delta}`, `${delta} nach unten seit gestern`];
    case "flat": return ["—", "Platz seit gestern unverändert"];
    default: return [];
  }
}

export function createDailyTop(root, {
  homeEntryKey, discoveryV2LogicalKey, loadDiscoveryProfile, selectFpRow, closeGlobalSearch,
  loadSeries, renderTop, renderRail, refreshStatuses, client = api,
}) {
  const document = root.ownerDocument;
  const find = id => root.querySelector(`#${id}`);
  const track = find("home-top-track");
  const rail = track?.closest(".home-rail");
  const charts = find("royal-charts");
  const detail = find("royal-chart-detail");
  const cardEntries = new WeakMap();
  const cache = new Map();
  const requests = new Map();
  const failures = new Set();
  const checked = new Set();
  let scope, day = "", configuration = "", homeMode = "today", fullMode = "today", selectedEntry = null;

  function visibleCandidates(mode) {
    const blocked = new Set(loadDiscoveryProfile()?.blocked_items || []);
    return (cache.get(mode)?.candidates || []).filter(({ identity, kind, item }) => {
      if (!identity || !item?.title || !(item.cover_url || item.backdrop_url)) return false;
      const entry = { kind, item };
      return ![identity, homeEntryKey(entry), discoveryV2LogicalKey(entry),
        item.tmdb_id && `${kind}:tmdb:${item.tmdb_id}`].some(key => blocked.has(key));
    });
  }

  function toEntries(candidates) {
    return candidates.map(({ kind, item, ...chart }) => ({ kind, item: { ...item, daily_top: chart } }));
  }

  function dailyTopEntries(mode = homeMode) {
    return toEntries(visibleCandidates(mode).slice(0, 10));
  }

  function message(mode, count) {
    if (requests.has(mode) && !count) return "Charts werden geladen …";
    if (failures.has(mode)) return "Charts konnten nicht geladen werden.";
    const payload = cache.get(mode);
    if (count) {
      return mode === "week" || mode === "month"
        ? `${payload.recorded_days} erfasste Tage in dieser Wertung` : "";
    }
    if (payload?.empty_reason === "no_snapshot") return "Für heute liegt noch kein Chart-Stand vor.";
    if (payload?.empty_reason === "insufficient_history") return "Für diese Wertung fehlen noch vergleichbare Tagesstände.";
    if (mode === "breakouts" && !payload?.candidates.length) return "Heute wurde kein ausreichender Anstieg gemessen.";
    if (mode === "new" && !payload?.candidates.length) return "Heute wurden keine Neueinsteiger bestätigt.";
    return "Keine Titel für diese Auswahl.";
  }

  function syncControls(container, mode) {
    container?.querySelectorAll("[data-chart-mode]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.chartMode === mode));
    });
  }

  function status(id, mode, count) {
    const node = find(id);
    if (!node) return;
    const label = message(mode, count);
    node.textContent = label;
    node.hidden = !label;
    if (!requests.has(mode) && (failures.has(mode) || cache.get(mode)?.empty_reason === "no_snapshot")) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "royal-chart-link";
      retry.dataset.chartRetry = mode;
      retry.textContent = "Erneut laden";
      node.append(" ", retry);
    }
  }

  function renderExpanded() {
    if (!charts?.open) return;
    const kind = find("royal-chart-kind").value;
    const genre = find("royal-chart-genre");
    const candidates = visibleCandidates(fullMode).filter(item => kind === "mixed" || item.kind === kind);
    const genres = [...new Set(candidates.flatMap(candidate => candidate.item.genres || []))];
    genres.sort((a, b) => a.localeCompare(b, "de"));
    const selection = genre.value;
    genre.replaceChildren(new Option("Alle Genres", ""), ...genres.map(name => new Option(name, name)));
    if (genres.includes(selection)) genre.value = selection;
    const filtered = candidates.filter(candidate => !genre.value || candidate.item.genres?.includes(genre.value));
    syncControls(charts, fullMode);
    renderRail("royal-chart-grid", toEntries(filtered), { ranked: true, showEmpty: false });
    find("royal-chart-grid").setAttribute("aria-busy", String(requests.has(fullMode)));
    status("royal-chart-status", fullMode, filtered.length);
  }

  function draw() {
    syncControls(rail, homeMode);
    const eyebrow = find("home-top-eyebrow");
    if (eyebrow) eyebrow.textContent = MODES[homeMode];
    track?.setAttribute("aria-label", `Top 10 · ${MODES[homeMode]}`);
    track?.setAttribute("aria-busy", String(requests.has(homeMode)));
    renderTop();
    status("home-top-status", homeMode, dailyTopEntries().length);
    renderExpanded();
  }

  async function load(mode, { force = false } = {}) {
    if (!scope?.active || requests.has(mode) || (!force && cache.has(mode))) return;
    const current = scope;
    const requestedDay = day;
    const token = {};
    let configurationChanged = false;
    requests.set(mode, token);
    failures.delete(mode);
    draw();
    try {
      const payload = await client.get("/api/v3/royal-charts?" + new URLSearchParams({ mode }), {
        signal: current.signal, timeoutMs: 90_000,
      });
      if (!current.active || day !== requestedDay || requests.get(mode) !== token) return;
      if (payload?.version !== 3 || !Array.isArray(payload.candidates)) throw new Error("Ungültige Chart-Antwort");
      if (configuration && configuration !== payload.scope) {
        configurationChanged = true;
        cache.clear();
        checked.clear();
        failures.clear();
        requests.clear();
        requests.set(mode, token);
      }
      configuration = payload.scope;
      cache.set(mode, payload);
      const entries = toEntries(visibleCandidates(mode)).filter(entry => {
        const key = homeEntryKey(entry);
        if (checked.has(key)) return false;
        checked.add(key);
        return true;
      });
      if (entries.length) void refreshStatuses?.(entries, () => { if (current.active) draw(); }, { signal: current.signal });
    } catch {
      if (current.active && requests.get(mode) === token) failures.add(mode);
    } finally {
      if (current.active && requests.get(mode) === token) {
        requests.delete(mode);
        draw();
        if (configurationChanged) {
          void load(homeMode);
          if (charts?.open) void load(fullMode);
        }
      }
    }
  }

  function refreshAtDayBoundary() {
    const currentDay = dayKey();
    if (day === currentDay) return;
    day = currentDay;
    cache.clear();
    requests.clear();
    failures.clear();
    void load(homeMode);
    if (charts?.open) void load(fullMode);
  }

  function scheduleMidnight() {
    const midnight = new Date(Date.now());
    midnight.setUTCHours(24, 0, 1, 0);
    scope.timeout(() => { refreshAtDayBoundary(); scheduleMidnight(); }, midnight.getTime() - Date.now());
  }

  function openDailyTopEntry(entry) {
    const item = entry?.item || {};
    if (!item.daily_top) return false;
    if (!(entry.kind === "movie" ? item.slug : item.base_slug)) return false;
    if (detail?.open) detail.close();
    if (charts?.open) charts.close();
    closeGlobalSearch?.();
    if (entry.kind === "movie") selectFpRow(item.slug, item);
    else loadSeries(item);
    return true;
  }

  function enhanceRankedCard(card, entry, rank) {
    const chart = entry?.item?.daily_top;
    if (!card || !rank || !chart) return card;
    cardEntries.set(card, entry);
    card.dataset.dailyTopScore = Number(chart.score || 0).toFixed(2);
    card.dataset.dailyTopGlobalRank = String(chart.global_rank);
    card.dataset.dailyTopDisplayRank = String(rank);
    const dismiss = card.querySelector(".home-card-art > .taste-v2-dismiss");
    if (dismiss) card.append(dismiss);
    const overlay = card.querySelector(".home-card-overlay");
    const [label, title] = movementBadge(chart.movement);
    let badge = overlay?.querySelector(".daily-top-movement");
    if (label && overlay) {
      if (!badge) {
        badge = document.createElement("span");
        overlay.insertBefore(badge, overlay.querySelector(".home-card-meta"));
      }
      badge.className = `daily-top-movement is-${chart.movement.direction}`;
      badge.textContent = label;
      badge.title = title;
      badge.setAttribute("aria-label", title);
    } else badge?.remove();
    let info = card.querySelector(".royal-chart-info");
    if (!info && detail) {
      info = document.createElement("button");
      info.type = "button";
      info.className = "royal-chart-info";
      info.textContent = "i";
      card.append(info);
    }
    info?.setAttribute("aria-label", `Chart-Details zu ${entry.item.title}`);
    return card;
  }

  function openExplanation(entry, rank) {
    selectedEntry = entry;
    const chart = entry.item.daily_top;
    const history = chart.history;
    find("royal-chart-detail-title").textContent = entry.item.title;
    const content = find("royal-chart-explanation");
    content.replaceChildren();
    function paragraph(label) {
      const node = document.createElement("p");
      node.textContent = label;
      content.append(node);
    }
    function heading(label) {
      const node = document.createElement("h3");
      node.textContent = label;
      content.append(node);
    }
    const previous = chart.movement?.previous_rank;
    const measured = history?.last_day ? ` am ${dateLabel.format(new Date(history.last_day))}` : "";
    paragraph(`Platz ${rank} in dieser Auswahl · Tagesscore${measured} ${number.format(chart.score)} von 100`);
    if (chart.mode_score !== chart.score) paragraph(`Wertung für diesen Modus: ${number.format(chart.mode_score)}`);
    if (history) {
      paragraph(`${history.days_charted} erfasste Chart-Tage · Bester Platz ${history.best_rank} · Zuletzt ${history.streak} in Folge`);
      if (previous) paragraph(`Gestern Platz ${previous}`);
    }
    heading("Warum steht dieser Titel in den Charts?");
    paragraph(`Popularität ${number.format(chart.components.popularity)} von 100 · Datenqualität ${CONFIDENCE[chart.confidence]}`);
    const strongest = Object.values(chart.popularity_observations || {})
      .sort((a, b) => b.value - a.value)[0];
    if (strongest) paragraph(`Stärkstes Signal: ${strongest.provider === "tmdb" ? "TMDB Trending" : strongest.provider}, Platz ${strongest.rank}`);
    for (const [provider, signal] of Object.entries(chart.provider_signals)) {
      if (["rating_rank", "recent_uploads", "unknown"].includes(signal.type)) continue;
      const grouped = signal.source !== provider ? ` · Signalgruppe ${signal.source === "tmdb" ? "TMDB" : signal.source}` : "";
      paragraph(`${provider} · ${SIGNALS[signal.type]} · Platz ${signal.rank}${grouped}`);
    }
    if (chart.tmdb_trend_rank) paragraph(`TMDB Trending · Platz ${chart.tmdb_trend_rank}`);
    const rating = chart.quality_source === "tmdb_votes"
      ? ` · TMDB ${entry.item.rating}/10 aus ${number.format(entry.item.vote_count)} Stimmen`
      : chart.quality_source === "rating_rank" ? " · aus Bewertungslisten" : "";
    paragraph(`Qualität ${number.format(chart.components.quality)} von 100${rating}`);
    for (const [provider, signal] of Object.entries(chart.provider_signals)) {
      if (signal.type === "rating_rank") paragraph(`${provider} · Bewertungsrang ${signal.rank}`);
    }
    paragraph(`Im Katalog gefunden bei ${chart.availability_providers.join(", ")}`);

    if (history) {
      heading("Chart-Verlauf");
      const timeline = document.createElement("ol");
      timeline.className = "royal-chart-timeline";
      const range = document.createElement("select");
      range.setAttribute("aria-label", "Zeitraum des Chart-Verlaufs");
      range.append(new Option("7 Tage", "last_7"), new Option("30 Tage", "last_30"));
      function renderTimeline() {
        timeline.replaceChildren(...history[range.value].map(point => {
          const node = document.createElement("li");
          const date = dateLabel.format(new Date(point.period));
          const label = point.rank ? `Platz ${point.rank}` : point.recorded ? "Außerhalb der Top 30" : "Kein Tagesstand";
          node.title = `${date} · ${label}`;
          node.append(date);
          const value = document.createElement("strong");
          value.textContent = point.rank ? `#${point.rank}` : point.recorded ? "—" : "·";
          value.setAttribute("aria-label", label);
          node.append(value);
          if (point.rank) node.style.setProperty("--chart-rank-strength", `${(31 - point.rank) * 100 / 30}%`);
          return node;
        }));
      }
      range.addEventListener("change", renderTimeline);
      renderTimeline();
      content.append(range, timeline);
    }
    detail.showModal();
  }

  return {
    entries: dailyTopEntries, enhance: enhanceRankedCard, open: openDailyTopEntry,
    refresh: refreshAtDayBoundary, renderExpanded,
    mount() {
      if (scope || !track) return;
      scope = createScope();
      scope.listen(root, "click", event => {
        const target = event.target;
        const toggle = target.closest("[data-chart-mode]");
        const card = target.closest(".home-card");
        const entry = cardEntries.get(card);
        if (toggle) {
          if (charts?.contains(toggle)) fullMode = toggle.dataset.chartMode;
          else { homeMode = toggle.dataset.chartMode; track.scrollLeft = 0; }
          draw();
          void load(toggle.dataset.chartMode);
        } else if (target.closest("[data-chart-retry]")) {
          void load(target.closest("[data-chart-retry]").dataset.chartRetry, { force: true });
        } else if (target.closest("[data-chart-open]") && charts) {
          fullMode = homeMode;
          charts.showModal();
          renderExpanded();
          void load(fullMode);
        } else if (target.closest("[data-chart-close]")) {
          target.closest("dialog")?.close();
        } else if (target.closest("[data-chart-title-open]")) {
          openDailyTopEntry(selectedEntry);
        } else if (entry && target.closest(".royal-chart-info")) {
          openExplanation(entry, Number(card.dataset.dailyTopDisplayRank));
        } else if (entry) {
          const action = target.closest("a, button, [role='button'], [data-card-action]");
          if (action && !action.classList.contains("home-card-primary-action")) return;
          if (openDailyTopEntry(entry)) { event.preventDefault(); event.stopImmediatePropagation(); }
        }
      }, true);
      if (charts) scope.listen(charts, "change", renderExpanded);
      scope.listen(document, "visibilitychange", () => { if (!document.hidden) refreshAtDayBoundary(); });
      refreshAtDayBoundary();
      scheduleMidnight();
    },
    unmount() {
      scope?.dispose();
      scope = null;
      cache.clear();
      requests.clear();
      failures.clear();
      checked.clear();
      day = "";
      configuration = "";
      if (detail?.open) detail.close();
      if (charts?.open) charts.close();
    },
  };
}
