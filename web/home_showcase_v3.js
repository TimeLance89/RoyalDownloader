/* Royal Home Showcase v3: live pulse metrics + editorial evening picks. */
(() => {
  "use strict";

  if (window.__royalHomeShowcaseV3Installed) return;

  const STYLE_ID = "royal-home-showcase-v3-style";
  const STYLE_HREF = "/styles/home-showcase.css?v=royal-20260820-1";

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const link = document.createElement("link");
    link.id = STYLE_ID;
    link.rel = "stylesheet";
    link.href = STYLE_HREF;
    document.head.appendChild(link);
  }

  function safeEntries() {
    try {
      return typeof homeAllEntries === "function" ? homeAllEntries().filter((entry) => entry?.item) : [];
    } catch {
      return [];
    }
  }

  function entryKey(entry) {
    try {
      if (typeof homeEntryKey === "function") return homeEntryKey(entry);
    } catch {
      // Fall through to the stable local key.
    }
    const item = entry?.item || {};
    return `${entry?.kind || "media"}:${item.slug || item.base_slug || item.id || item.title || "unknown"}`;
  }

  function uniqueEntries(entries) {
    const seen = new Set();
    return entries.filter((entry) => {
      const key = entryKey(entry);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function mediaFor(entry) {
    try {
      return typeof homeEntryMedia === "function" ? homeEntryMedia(entry) : (entry?.item || {});
    } catch {
      return entry?.item || {};
    }
  }

  function statusFor(entry) {
    const media = mediaFor(entry);
    try {
      return typeof mediaJellyfinStatus === "function" ? mediaJellyfinStatus(media) : "checking";
    } catch {
      return "checking";
    }
  }

  function profileSnapshot() {
    try {
      return typeof loadDiscoveryProfile === "function" ? loadDiscoveryProfile() : {};
    } catch {
      return {};
    }
  }

  function favoriteGenre(profile) {
    try {
      if (typeof favoriteDiscoveryGenre === "function") return favoriteDiscoveryGenre(profile);
    } catch {
      // Compute a local fallback below.
    }
    return Object.entries(profile?.genres || {})
      .filter(([, score]) => Number(score) > 0.25)
      .sort((left, right) => Number(right[1]) - Number(left[1]))[0]?.[0] || "";
  }

  function createShell() {
    const tab = document.getElementById("tab-home");
    const rails = tab?.querySelector(".home-rails");
    if (!tab || !rails) return null;

    let shell = document.getElementById("home-showcase-v3");
    if (shell) return shell;

    shell = document.createElement("section");
    shell.id = "home-showcase-v3";
    shell.className = "home-showcase-v3";
    shell.setAttribute("aria-labelledby", "home-showcase-title");
    shell.innerHTML = `
      <header class="home-showcase-head">
        <div class="home-showcase-heading">
          <span class="home-showcase-kicker">ROYAL PULSE</span>
          <h2 id="home-showcase-title">Dein Kino auf einen Blick.</h2>
          <p id="home-showcase-context">Royal verbindet Katalog, Jellyfin und deinen Geschmack zu einem persönlichen Programm.</p>
        </div>
        <div class="home-showcase-actions" aria-label="Schnellaktionen">
          <button id="home-showcase-mood" class="home-showcase-action is-primary" type="button">
            <span aria-hidden="true">✦</span> Abendmodus
          </button>
          <button id="home-showcase-library" class="home-showcase-action" type="button">
            <span aria-hidden="true">▣</span> Meine Liste
          </button>
        </div>
      </header>
      <div id="home-pulse-grid" class="home-pulse-grid" aria-label="Royal Status"></div>
      <div class="home-showcase-editorial-head">
        <div>
          <span class="home-showcase-kicker">HEUTE ABEND</span>
          <h3>Drei Wege in den Filmabend.</h3>
        </div>
        <p>Persönlich, überraschend und serienreif – direkt aus deinen aktiven Quellen.</p>
      </div>
      <div id="home-tonight-grid" class="home-tonight-grid" aria-label="Auswahl für heute Abend"></div>
    `;
    rails.insertAdjacentElement("beforebegin", shell);

    shell.querySelector("#home-showcase-mood")?.addEventListener("click", (event) => {
      if (typeof openMoodMatch === "function") openMoodMatch(event.currentTarget);
    });
    shell.querySelector("#home-showcase-library")?.addEventListener("click", () => {
      if (typeof switchTab === "function") switchTab("bibliothek");
    });
    return shell;
  }

  function metricCard({ mark, value, label, detail, tone = "" }) {
    const card = document.createElement("article");
    card.className = `home-pulse-card${tone ? ` is-${tone}` : ""}`;

    const icon = document.createElement("span");
    icon.className = "home-pulse-mark";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = mark;

    const copy = document.createElement("div");
    const number = document.createElement("strong");
    number.textContent = value;
    const title = document.createElement("span");
    title.textContent = label;
    const small = document.createElement("small");
    small.textContent = detail;
    copy.append(number, title, small);
    card.append(icon, copy);
    return card;
  }

  function renderPulse(shell, entries, profile) {
    const grid = shell.querySelector("#home-pulse-grid");
    if (!grid) return;

    const unique = uniqueEntries(entries);
    const owned = unique.filter((entry) => statusFor(entry) === "owned").length;
    const missing = unique.filter((entry) => statusFor(entry) === "missing").length;
    const fresh = uniqueEntries([
      ...(typeof state !== "undefined" ? (state.home?.newMovies || []) : []).map((item) => ({ kind: "movie", item })),
      ...(typeof state !== "undefined" ? (state.home?.newSeries || []) : []).map((item) => ({ kind: "series", item })),
    ]).length;
    const interactions = Number(profile?.interactions || 0);
    const genre = favoriteGenre(profile);

    grid.replaceChildren(
      metricCard({
        mark: "◆",
        value: String(unique.length || "—"),
        label: "Titel im Mix",
        detail: unique.length ? "aus deinen aktiven Quellen" : "Katalog wird aufgebaut",
      }),
      metricCard({
        mark: "✓",
        value: String(owned || "—"),
        label: "Schon in Jellyfin",
        detail: owned ? "direkt in deiner Bibliothek" : "Bibliothek wird abgeglichen",
        tone: "owned",
      }),
      metricCard({
        mark: "+",
        value: String(missing || fresh || "—"),
        label: missing ? "Noch offen" : "Frisch im Programm",
        detail: missing ? "noch nicht in Jellyfin" : `${fresh || 0} neue Katalogtitel`,
        tone: "fresh",
      }),
      metricCard({
        mark: "✦",
        value: interactions ? String(interactions) : "NEU",
        label: "Taste-Signale",
        detail: genre ? `Fokus: ${genre}` : "lernt mit jeder Auswahl",
        tone: "taste",
      }),
    );

    const context = shell.querySelector("#home-showcase-context");
    if (context) {
      context.textContent = interactions >= 2
        ? `Royal kennt bereits ${interactions} deiner Signale${genre ? ` und erkennt ${genre} als starken Geschmacksschwerpunkt` : ""}.`
        : "Royal verbindet Katalog, Jellyfin und deinen Geschmack zu einem persönlichen Programm.";
    }
  }

  function pickBuckets(entries) {
    let lanes = null;
    try {
      lanes = typeof homeDiscoveryLanes === "function" ? homeDiscoveryLanes() : null;
    } catch {
      lanes = null;
    }

    const fallback = uniqueEntries(entries);
    const definitions = [
      {
        eyebrow: "DEIN MATCH",
        title: "Genau dein Ding",
        note: "Aus deinem bisherigen Geschmack",
        entries: lanes?.personal || fallback,
      },
      {
        eyebrow: "GEHEIMTIPP",
        title: "Etwas, das du übersiehst",
        note: "Bewusst abseits deiner ersten Reihe",
        entries: lanes?.gems?.length ? lanes.gems : (lanes?.explore || fallback),
      },
      {
        eyebrow: "SERIENABEND",
        title: "Noch eine Folge",
        note: "Aktuell stark in deinen Serienquellen",
        entries: (lanes?.series || fallback).filter((entry) => entry.kind === "series"),
      },
    ];

    const used = new Set();
    return definitions.map((definition) => {
      let entry = uniqueEntries(definition.entries || []).find((candidate) => !used.has(entryKey(candidate)));
      if (!entry) entry = fallback.find((candidate) => !used.has(entryKey(candidate)));
      if (entry) used.add(entryKey(entry));
      return { ...definition, entry };
    });
  }

  function artworkUrl(media) {
    const artwork = media.backdrop_url || media.cover_url || "";
    if (!artwork) return "";
    try {
      return typeof api !== "undefined" && typeof api.coverUrl === "function" ? api.coverUrl(artwork) : artwork;
    } catch {
      return artwork;
    }
  }

  function openPick(entry) {
    if (!entry || typeof openHomeEntry !== "function") return;
    const item = entry.item || {};
    const key = entry.kind === "movie" ? item.slug : entry.kind === "anime" ? item.id : item.base_slug;
    if (key) openHomeEntry(entry.kind, key);
  }

  function createPick(definition, index) {
    const entry = definition.entry;
    if (!entry) {
      const empty = document.createElement("article");
      empty.className = `home-tonight-card is-skeleton${index === 0 ? " is-lead" : ""}`;
      empty.setAttribute("aria-hidden", "true");
      empty.innerHTML = "<span></span><span></span><span></span>";
      return empty;
    }

    const media = mediaFor(entry);
    const button = document.createElement("button");
    button.type = "button";
    button.className = `home-tonight-card${index === 0 ? " is-lead" : ""}`;
    button.setAttribute("aria-label", `${definition.title}: ${media.title || "Details öffnen"}`);

    const art = artworkUrl(media);
    if (art) button.style.setProperty("--home-tonight-art", `url("${art.replace(/"/g, "%22")}")`);
    else button.classList.add("has-no-art");

    const shade = document.createElement("span");
    shade.className = "home-tonight-shade";
    shade.setAttribute("aria-hidden", "true");

    const copy = document.createElement("span");
    copy.className = "home-tonight-copy";
    const eyebrow = document.createElement("small");
    eyebrow.className = "home-tonight-eyebrow";
    eyebrow.textContent = definition.eyebrow;
    const title = document.createElement("strong");
    title.textContent = media.title || definition.title;
    title.translate = false;
    const meta = document.createElement("span");
    meta.className = "home-tonight-meta";
    meta.textContent = [
      media.year || (media.first_air_date ? String(media.first_air_date).slice(0, 4) : ""),
      media.rating ? `★ ${media.rating}` : "",
      ...(media.genres || []).slice(0, 2),
    ].filter(Boolean).join(" · ") || (entry.kind === "series" ? "Serie" : "Film");
    const reason = document.createElement("span");
    reason.className = "home-tonight-reason";
    reason.textContent = definition.note;
    copy.append(eyebrow, title, meta, reason);

    const open = document.createElement("span");
    open.className = "home-tonight-open";
    open.setAttribute("aria-hidden", "true");
    open.textContent = "→";

    button.append(shade, copy, open);
    button.addEventListener("click", () => openPick(entry));
    return button;
  }

  function renderShowcase() {
    const shell = createShell();
    if (!shell) return false;
    const entries = safeEntries();
    const profile = profileSnapshot();
    renderPulse(shell, entries, profile);

    const grid = shell.querySelector("#home-tonight-grid");
    if (grid) {
      grid.replaceChildren(...pickBuckets(entries).map(createPick));
    }
    return true;
  }

  function install() {
    ensureStyles();
    if (!renderShowcase()) return false;
    if (window.__royalHomeShowcaseV3Installed) return true;
    window.__royalHomeShowcaseV3Installed = true;

    const rails = document.querySelector("#tab-home .home-rails");
    if (rails && typeof MutationObserver === "function") {
      let frame = 0;
      const observer = new MutationObserver(() => {
        window.cancelAnimationFrame(frame);
        frame = window.requestAnimationFrame(renderShowcase);
      });
      observer.observe(rails, { childList: true, subtree: true });
      window.__royalHomeShowcaseV3Observer = observer;
    }

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && typeof state !== "undefined" && state.tab === "home") renderShowcase();
    });
    return true;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      if (install()) return;
      let attempts = 0;
      const timer = window.setInterval(() => {
        attempts += 1;
        if (install() || attempts >= 40) window.clearInterval(timer);
      }, 100);
    }, { once: true });
  } else if (!install()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (install() || attempts >= 40) window.clearInterval(timer);
    }, 100);
  }
})();
