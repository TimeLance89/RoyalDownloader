import { createScope } from "../../core/lifecycle.js";

export function createMoviePresentation(catalogRoot, detailRoot, {
  locale, movieState, getQueuedSlugs, coverUrl, subscriptionFor, openSubscription,
  activateResultCard, applyFpSmartFilters, configureFpDetailAction, configureFpTrailer, createResultCardVisual, dedupeCatalogMedia, discardObservedResultPosters, fpMetadataPreloadItems, fpSmartFilteredResults, fpSmartFilters, homeMovieBySlug, mediaJellyfinStatus, mergeFpMetadata, preloadTmdbMetadata, refreshFpJellyfinStatus, refreshMovieFeatureCandidates, renderFpAbout, renderFpExtras, renderFpSimilarTitles, scheduleFpCatalogRefresh, selectFpRow, setCatalogJellyfinBadge, syncResultCardPoster, toggleFpPick, updateTasteFeedbackButtons,
}) {
  const document = catalogRoot.ownerDocument;
  const byId = id => catalogRoot.querySelector(`#${id}`) || detailRoot.querySelector(`#${id}`);
  const actions = new WeakMap();
  let scope = null, detailScope = null;
  function bind(node, type, callback) { actions.set(node, { type, callback }); }
  function dispatch(event) {
    for (let node = event.target; node; node = node.parentElement) {
      const action = actions.get(node);
      if (action?.type === event.type) { action.callback(event); return; }
      if (node === catalogRoot || node === detailRoot) return;
    }
  }
  function fpStatusMessage() {
    const filteredResults = fpSmartFilteredResults();
    const visibleSlugs = new Set(filteredResults.map((r) => r.slug));
    const visiblePicks = [...getQueuedSlugs()].filter((s) => visibleSlugs.has(s)).length;
    const otherPicks = getQueuedSlugs().size - visiblePicks;
    let msg;
    if (movieState.searchActive) {
      msg = `${filteredResults.length} Filme auf TMDB`;
    } else if (movieState.activeGenre === "Alle Genres") {
      msg = `${filteredResults.length} von ${movieState.results.length} Treffern`;
    } else {
      msg = `${movieState.activeGenre} · ${filteredResults.length} von ${movieState.results.length} Treffern`;
    }
    if (getQueuedSlugs().size) {
      const extra = otherPicks ? `  ·  ${otherPicks} von anderen Seiten` : "";
      msg += `  ·  ${getQueuedSlugs().size} markiert${extra}`;
    }
    return msg;
  }

  function setActiveGenreFilter(genre) {
    const activeGenre = genre || "Alle Genres";
    movieState.activeGenre = activeGenre;
    const activeLabel = byId("genre-active");
    if (activeLabel) activeLabel.textContent = activeGenre === "Alle Genres" ? "Alle Filme" : activeGenre;
    const select = byId("movie-filter-genre");
    if (select) select.value = activeGenre;
  }

  function mergeCatalogItems(current, incoming, keyFor) {
    const merged = current.slice();
    const known = new Set(current.map(keyFor));
    for (const item of incoming) {
      const key = keyFor(item);
      if (!key || known.has(key)) continue;
      known.add(key);
      merged.push(item);
    }
    const looksLikeMedia = merged.some(item => item?.title && (
      item.slug || item.base_slug || item.sample_slug || item.tmdb_id
    ));
    return looksLikeMedia ? dedupeCatalogMedia(merged) : merged;
  }

  function mergeCatalogSources(current, incoming, append) {
    const cleanIncoming = Array.isArray(incoming)
      ? incoming.filter((source) => Number(source.count) > 0)
      : [];
    if (!append) return cleanIncoming;
    const merged = new Map(current.map((source) => [source.key || source.label, { ...source }]));
    for (const source of cleanIncoming) {
      const key = source.key || source.label;
      const existing = merged.get(key);
      if (existing) existing.count = Number(existing.count || 0) + Number(source.count || 0);
      else merged.set(key, { ...source });
    }
    return [...merged.values()];
  }

  function updateFpInfiniteState() {
    const sentinel = byId("fp-infinite");
    if (!sentinel) return;
    const label = byId("fp-infinite-label");
    const retry = byId("fp-infinite-retry");
    const browsable = Boolean(movieState.category && !movieState.searchActive && movieState.results.length);
    sentinel.classList.toggle("hidden", !browsable);
    if (!browsable) return;

    const count = movieState.results.length;
    sentinel.setAttribute("aria-busy", String(movieState.loadingMore));
    retry.hidden = !movieState.loadError;
    retry.textContent = movieState.loadError ? "Erneut versuchen" : "Weitere laden";
    if (movieState.loadingMore) {
      sentinel.dataset.state = "loading";
      label.textContent = "Weitere Filme werden geladen …";
    } else if (movieState.loadError) {
      sentinel.dataset.state = "error";
      label.textContent = `Nachladen fehlgeschlagen · ${count} Filme geladen`;
    } else if (movieState.lastPageFull) {
      sentinel.dataset.state = "ready";
      label.textContent = `${count} Filme geladen · Weiter scrollen`;
    } else {
      sentinel.dataset.state = "complete";
      label.textContent = `${count} Filme geladen · Ende des Katalogs`;
    }
    const sourceSummary = movieState.sources
      .map((source) => `${source.label} ${source.count}`)
      .join(" · ");
    sentinel.title = sourceSummary;
  }

  // Bestes bekanntes Jahr eines Filmtreffers. Anbieterlisten liefern teils ein
  // falsches Jahr (Re-Release/Scraping-Fehler), das den jahrgenauen
  // Jellyfin-Abgleich sonst fälschlich scheitern lässt und im UI verkehrt
  // angezeigt wird. Das per TMDB aufgelöste Jahr ist verlässlicher.
  function fpResultYear(result) {
    return movieState.metadataCache[result.slug]?.year || result.year || "";
  }




  function setFpJellyfinBadge(badge, status) {
    const normalized = typeof status === "boolean" ? (status ? "owned" : "missing") : status;
    setCatalogJellyfinBadge(badge, normalized);
    badge.classList.add("jellyfin-badge");
  }

  function setFpPosterJellyfinBadge(badge, status) {
    const normalized = typeof status === "boolean" ? (status ? "owned" : "missing") : status;
    setCatalogJellyfinBadge(badge, normalized);
    badge.classList.add("result-card-library-badge");
    badge.textContent = {
      owned: "In Jellyfin",
      missing: "Nicht in Jellyfin",
      checking: "Jellyfin wird geprüft",
      unavailable: "Jellyfin nicht erreichbar",
      blocked: "Jellyfin-Statusanfrage blockiert",
      unconfigured: "Jellyfin nicht verbunden",
      ambiguous: "Jellyfin-Zuordnung unklar",
    }[normalized] || "Jellyfin wird geprüft";
    badge.hidden = false;
  }

  function updateFpJellyfinBadges() {
    const resultsBySlug = new Map(movieState.results.map((result) => [result.slug, result]));
    for (const row of catalogRoot.querySelectorAll("#fp-results .row")) {
      const result = resultsBySlug.get(row.dataset.slug);
      const badge = row.querySelector(".jellyfin-badge");
      if (result && badge) setFpJellyfinBadge(badge, mediaJellyfinStatus(result));
      const posterBadge = row.querySelector(".result-card-library-badge");
      if (result && posterBadge) setFpPosterJellyfinBadge(posterBadge, mediaJellyfinStatus(result));
    }
    const selected = resultsBySlug.get(movieState.selectedSlug) || homeMovieBySlug(movieState.selectedSlug)
      || movieState.metadataCache[movieState.selectedSlug];
    if (selected) {
      const selectedStatus = mediaJellyfinStatus(selected);
      setFpDetailJellyfinStatus(selectedStatus === "owned" ? true
        : selectedStatus === "missing" ? false : selectedStatus);
      const movie = movieState.moviesCache[selected.slug]
        || metadataPreviewMovie(movieState.metadataCache[selected.slug] || basicMovieMetadata(selected));
      configureFpDetailAction(selected.slug, movie, movieState.detail?.slug === selected.slug
        ? movieState.detail.availabilityState === "checking" : !movieState.moviesCache[selected.slug]);
    }
    if (fpSmartFilters().availability !== "all") applyFpSmartFilters();
  }



  function fpResultMedia(result) {
    return {
      ...result,
      ...(movieState.metadataCache[result.slug] || {}),
      ...(movieState.moviesCache[result.slug] || {}),
      slug: result.slug,
    };
  }

  function fpResultAvailability(result) {
    const movie = movieState.moviesCache[result.slug];
    const queued = getQueuedSlugs().has(result.slug);
    if (queued) return { label: "In Queue", tag: "picked" };
    if (movie) {
      if (!movie.hosters || movie.hosters.length === 0) return { label: "Kein Hoster", tag: "novoe" };
      return {
        label: movie.provider_count ? `${movie.provider_count} Anbieter` : (movie.hoster_label || "Bereit"),
        tag: "ready",
      };
    }
    if (String(result.slug || "").startsWith("tmdb:")) return { label: "Auswählen", tag: "idle" };
    if (movieState.pendingPreload?.has(result.slug)) return { label: "Lädt …", tag: "pending" };
    return { label: "Wird geprüft", tag: "idle" };
  }

  function findFpResultCard(slug) {
    return [...catalogRoot.querySelectorAll("#fp-results .result-card")]
      .find((row) => row.dataset.slug === slug) || null;
  }

  function updateFpResultCard(slug) {
    const result = movieState.results.find((item) => item.slug === slug);
    const row = findFpResultCard(slug);
    if (!result || !row) return;
    const visual = row.querySelector(".result-card-visual");
    const media = fpResultMedia(result);
    row.setAttribute("aria-label", [result.title, result.year].filter(Boolean).join(", "));
    const title = row.querySelector(".result-card-title");
    if (title) title.textContent = result.title;
    if (visual) {
      syncResultCardPoster(visual, media);
      const posterBadge = visual.querySelector(".result-card-library-badge");
      if (posterBadge) setFpPosterJellyfinBadge(posterBadge, mediaJellyfinStatus(result));
    }
    const availability = fpResultAvailability(result);
    const stateLabel = row.querySelector(".result-card-state");
    if (stateLabel) {
      stateLabel.className = `result-card-state status-${availability.tag}`;
      stateLabel.textContent = availability.label;
    }
    const subtitle = row.querySelector(".result-card-subtitle");
    if (subtitle) {
      const resolved = movieState.moviesCache[result.slug];
      subtitle.textContent = (resolved?.source_providers || []).map((source) => source.label).join(" · ")
        || (media.genres || []).slice(0, 2).join(" · ")
        || "Film";
    }
    const rating = row.querySelector(".result-card-rating");
    if (rating) rating.textContent = media.rating ? `★ ${media.rating}` : "★ —";
    const yearEl = row.querySelector(".result-card-year");
    if (yearEl) yearEl.textContent = fpResultYear(result) || "Jahr offen";
  }

  function syncFpDetailQueueAction() {
    const slug = movieState.selectedSlug;
    const detailPanel = byId("fp-detail-panel");
    if (!slug || detailPanel.classList.contains("is-empty")) return;
    const movie = movieState.moviesCache[slug];
    const metadata = movieState.metadataCache[slug];
    if (movie) configureFpDetailAction(slug, movie, false);
    else if (metadata) configureFpDetailAction(slug, metadataPreviewMovie(metadata), true);
  }

  function syncFpQueueIndicators() {
    for (const result of movieState.results) {
      const row = findFpResultCard(result.slug);
      if (!row) continue;
      const queued = getQueuedSlugs().has(result.slug);
      row.classList.toggle("queued", queued);
      const toggle = row.querySelector(".result-queue-toggle");
      if (toggle) {
        toggle.classList.toggle("is-queued", queued);
        toggle.textContent = queued ? "✓" : "+";
        toggle.setAttribute("aria-label", queued
          ? `${result.title} aus der Queue entfernen`
          : `${result.title} zur Queue hinzufügen`);
      }
      const availability = fpResultAvailability(result);
      const stateLabel = row.querySelector(".result-card-state");
      if (stateLabel) {
        stateLabel.className = `result-card-state status-${availability.tag}`;
        stateLabel.textContent = availability.label;
      }
    }
    if (movieState.results.length) {
      byId("fp-status").textContent = fpStatusMessage();
    }
    syncFpDetailQueueAction();
    if (fpSmartFilters().availability === "queued") applyFpSmartFilters();
  }

  function updateFpResultSelection() {
    for (const row of catalogRoot.querySelectorAll("#fp-results .row")) {
      const selected = row.dataset.slug === movieState.selectedSlug;
      row.classList.toggle("selected", selected);
      row.setAttribute("aria-current", String(selected));
    }
  }

  function renderFpResults(appendFrom = 0) {
    const container = byId("fp-results");
    if (appendFrom <= 0) {
      discardObservedResultPosters(container);
      container.innerHTML = "";
    }

    for (const result of movieState.results.slice(appendFrom)) {
      const selected = result.slug === movieState.selectedSlug;
      const queued = getQueuedSlugs().has(result.slug);
      const availability = fpResultAvailability(result);
      const media = fpResultMedia(result);

      const row = document.createElement("div");
      row.className = "row result-card" + (selected ? " selected" : "") + (queued ? " queued" : "");
      row.dataset.slug = result.slug;
      row.setAttribute("aria-current", String(selected));
      row.setAttribute("aria-label", [result.title, result.year].filter(Boolean).join(", "));

      const visual = createResultCardVisual(media, result.title, "movie", mediaJellyfinStatus(result));

      const copy = document.createElement("span");
      copy.className = "result-card-copy";
      const title = document.createElement("strong");
      title.className = "result-card-title";
      title.translate = false;
      title.textContent = result.title;
      const subtitle = document.createElement("span");
      subtitle.className = "result-card-subtitle";
      subtitle.textContent = (media.genres || []).slice(0, 2).join(" · ") || "Film";
      const meta = document.createElement("span");
      meta.className = "result-card-meta";
      const rating = document.createElement("span");
      rating.className = "result-card-rating";
      rating.textContent = media.rating ? `★ ${media.rating}` : "★ —";
      const year = document.createElement("span");
      year.className = "result-card-year";
      year.textContent = fpResultYear(result) || "Jahr offen";
      const status = document.createElement("span");
      status.className = `result-card-state status-${availability.tag}`;
      status.textContent = availability.label;
      const jellyfin = document.createElement("span");
      setFpJellyfinBadge(jellyfin, mediaJellyfinStatus(result));
      meta.append(rating, year, status, jellyfin);
      copy.append(title, subtitle, meta);

      const queueToggle = document.createElement("button");
      queueToggle.type = "button";
      queueToggle.className = "pick-flag result-queue-toggle" + (queued ? " is-queued" : "");
      queueToggle.textContent = queued ? "✓" : "+";
      queueToggle.setAttribute("aria-label", queued
        ? `${result.title} aus der Queue entfernen`
        : `${result.title} zur Queue hinzufügen`);
      bind(queueToggle, "click", (event) => {
        event.stopPropagation();
        toggleFpPick(result.slug);
      });

      row.append(visual, copy, queueToggle);
      activateResultCard(row, () => selectFpRow(result.slug));
      container.appendChild(row);
    }

    applyFpSmartFilters();
  }

  function applyFpResults(data, { append = false, metadataPrepared = false, backgroundRefresh = false } = {}) {
    scheduleFpCatalogRefresh(Boolean(data.refresh_pending));
    const incoming = dedupeCatalogMedia(data?.results || []);
    const renderedCards = catalogRoot.querySelectorAll("#fp-results .result-card");
    const preserveRenderedCards = !append
      && incoming.length === movieState.results.length
      && renderedCards.length === incoming.length
      && incoming.every((result, index) => result.slug === movieState.results[index]?.slug);
    for (const result of incoming) {
      if (result?.tmdb_id) {
        movieState.metadataCache[result.slug] = mergeFpMetadata(
          movieState.metadataCache[result.slug], result,
        );
      }
    }
    const appendFrom = append ? movieState.results.length : 0;
    movieState.results = append
      ? mergeCatalogItems(movieState.results, incoming, (item) => item.slug)
      : incoming;
    const responsePage = Number(data.page || 1);
    // Eine wegen langsamer Quellen nur teilweise gelieferte Folgeseite wird
    // beim naechsten Scrollen erneut angefordert. Bereits sichtbare Treffer
    // bleiben dank mergeCatalogItems stabil und fehlende Filme gehen nicht
    // durch ein vorschnelles Weiterschalten auf die naechste Seite verloren.
    movieState.page = append && data.page_complete === false
      ? Math.max(1, responsePage - 1)
      : responsePage;
    movieState.category = data.category ?? movieState.category;
    movieState.lastPageFull = Boolean(data.has_more ?? data.last_page_full);
    movieState.sources = mergeCatalogSources(movieState.sources, data.sources, append);
    movieState.loadingMore = false;
    movieState.loadError = "";
    if (!append && !backgroundRefresh) movieState.selectedSlug = null;
    if (!append) movieState.metadataRequestSeq += 1;
    const metadataItems = fpMetadataPreloadItems(incoming);
    const pendingSlugs = new Set(
      metadataPrepared ? [] : metadataItems.map((item) => item.slug),
    );
    movieState.pendingPreload = append && movieState.pendingPreload
      ? movieState.pendingPreload
      : new Set();
    for (const slug of pendingSlugs) movieState.pendingPreload.add(slug);
    if (preserveRenderedCards) {
      for (const result of incoming) updateFpResultCard(result.slug);
      byId("fp-status").textContent = fpStatusMessage();
    } else {
      renderFpResults(appendFrom);
    }
    void refreshFpJellyfinStatus(incoming);
    refreshMovieFeatureCandidates();
    updateFpInfiniteState();
    if (metadataItems.length && !metadataPrepared) {
      void preloadTmdbMetadata(movieState.metadataRequestSeq, metadataItems);
    } else if (!movieState.pendingPreload.size) {
      movieState.pendingPreload = null;
    }
  }




  function basicMovieMetadata(item) {
    return {
      ...item,
      title: item.title,
      year: item.year || "",
      cover_url: item.cover_url || "",
      backdrop_url: item.backdrop_url || "",
      description: item.description || "",
      genres: Array.isArray(item.genres) ? item.genres : [],
      runtime: item.runtime || "",
    };
  }

  function metadataPreviewMovie(metadata) {
    return {
      ...metadata,
      hosters: [],
      hoster_route: "wird geladen",
      hoster_score: null,
      hoster_fallback_count: 0,
    };
  }

  function renderFpDetailItems(id, values, emptyText = "") {
    const element = byId(id);
    element.innerHTML = "";
    const items = (values || []).filter(Boolean);
    if (!items.length && emptyText) items.push(emptyText);
    for (const value of items) {
      const item = document.createElement("span");
      item.textContent = value;
      element.appendChild(item);
    }
  }

  function setFpDetailAvailability(text, state = "ready") {
    const badge = byId("fp-detail-availability");
    badge.textContent = text;
    badge.className = `detail-availability is-${state}`;
  }

  function setFpDetailJellyfinStatus(owned) {
    const badge = byId("fp-detail-jellyfin");
    const label = badge.querySelector("strong");
    badge.className = "detail-jellyfin";
    if (owned === true) {
      badge.classList.add("is-owned");
      label.textContent = "In Jellyfin vorhanden";
      return;
    }
    if (owned === false) {
      badge.classList.add("is-missing");
      label.textContent = "Nicht in Jellyfin";
      return;
    }
    if (owned === "unavailable") {
      label.textContent = "Jellyfin nicht erreichbar";
      return;
    }
    if (owned === "blocked") {
      label.textContent = "Jellyfin-Statusanfrage blockiert";
      return;
    }
    if (owned === "unconfigured") {
      label.textContent = "Jellyfin nicht eingerichtet";
      return;
    }
    badge.classList.add("is-checking");
    label.textContent = "Jellyfin wird geprüft";
  }

  function fpDetailJellyfinValue(slug, movie) {
    const status = movieState.metadataCache[slug]?.jellyfin_status;
    if (status) return status === "owned" ? true : status === "missing" ? false : status;
    const catalogItem = movieState.results.find((item) => item.slug === slug)
      || homeMovieBySlug(slug);
    if (typeof catalogItem?.in_jellyfin === "boolean") return catalogItem.in_jellyfin;
    if (typeof movie?.in_jellyfin === "boolean") return movie.in_jellyfin;
    return null;
  }

  function formatMovieDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) return value || "—";
    const date = new Date(`${value}T00:00:00Z`);
    return new Intl.DateTimeFormat(locale(), {
      day: "2-digit", month: "long", year: "numeric", timeZone: "UTC",
    }).format(date);
  }

  function formatMovieNumber(value) {
    const number = Number(value || 0);
    return number > 0 ? new Intl.NumberFormat(locale()).format(number) : "";
  }

  function formatMovieMoney(value) {
    const number = Number(value || 0);
    if (number <= 0) return "";
    return new Intl.NumberFormat(locale(), {
      style: "currency", currency: "USD", maximumFractionDigits: 0,
      notation: number >= 1_000_000 ? "compact" : "standard",
    }).format(number);
  }

  function movieCertificationLabel(movie) {
    const certification = String(movie.certification || "").trim();
    if (!certification) return "Nicht angegeben";
    const country = String(movie.certification_country || "").toUpperCase();
    if (country === "DE") return `FSK ${certification}`;
    return country ? `${country} ${certification}` : certification;
  }

  function movieStatusLabel(status) {
    return ({
      Released: "Veröffentlicht",
      "Post Production": "Postproduktion",
      "In Production": "In Produktion",
      Planned: "Geplant",
      Rumored: "Gerücht",
      Canceled: "Abgebrochen",
    })[status] || status || "";
  }

  function setFpDetailText(id, value, fallback = "—") {
    byId(id).textContent = value || fallback;
  }

  function renderFpCast(cast, tmdbUrl) {
    const section = byId("fp-detail-cast-section");
    const container = byId("fp-detail-cast");
    const link = byId("fp-detail-tmdb-link");
    const members = Array.isArray(cast) ? cast.filter((member) => member?.name) : [];
    section.hidden = !members.length;
    container.innerHTML = "";
    const safeTmdbUrl = /^https:\/\/www\.themoviedb\.org\/movie\/\d+$/.test(tmdbUrl || "");
    link.href = safeTmdbUrl ? tmdbUrl : "https://www.themoviedb.org";
    if (!members.length) return;
    for (const member of members) {
      const card = document.createElement("div");
      card.className = "detail-cast-card";
      const portrait = document.createElement("div");
      portrait.className = "detail-cast-portrait";
      if (member.profile_url) {
        const image = document.createElement("img");
        image.src = coverUrl(member.profile_url);
        image.alt = "";
        image.loading = "lazy";
        portrait.appendChild(image);
      } else {
        portrait.textContent = member.name
          .split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
      }
      const copy = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = member.name;
      const role = document.createElement("small");
      role.textContent = member.character || "Besetzung";
      copy.append(name, role);
      card.append(portrait, copy);
      container.appendChild(card);
    }
  }



  function configureFpSubscriptionAction(slug, movie) {
    const button = byId("fp-detail-subscribe");
    const fallback = movieState.results.find((item) => item.slug === slug) || homeMovieBySlug(slug);
    const resolvedMovie = {
      ...(fallback || {}),
      ...(movie || {}),
      title: movie?.title || fallback?.title || "Film",
      year: movie?.year || fallback?.year || "",
    };
    const entry = subscriptionFor(slug, resolvedMovie);
    button.disabled = !slug;
    button.dataset.slug = slug || "";
    button.classList.toggle("is-active", Boolean(entry));
    button.textContent = entry ? "⚙ Film-Abo" : "+ Film abonnieren";
  }

  function openSelectedMovieSubscription() {
    const button = byId("fp-detail-subscribe");
    const slug = button?.dataset.slug || movieState.selectedSlug;
    if (!slug) return;
    const fallback = movieState.results.find((item) => item.slug === slug) || homeMovieBySlug(slug);
    const movie = {
      ...(fallback || {}),
      ...(movieState.metadataCache[slug] || {}),
      ...(movieState.moviesCache[slug] || {}),
    };
    openSubscription(slug, movie);
  }

  function presentMovieSubscriptions() {
    if (movieState.selectedSlug) {
      const movie = movieState.moviesCache[movieState.selectedSlug]
        || movieState.metadataCache[movieState.selectedSlug];
      if (movie) configureFpSubscriptionAction(movieState.selectedSlug, movie);
    }
  }

  function movieQualityRank(value) {
    const text = String(value || "").toUpperCase();
    const resolution = Number(text.match(/(\d{3,4})\s*P?/)?.[1] || 0);
    if (resolution) return resolution;
    if (text.includes("UHD") || text.includes("4K")) return 2160;
    if (text.includes("FULL HD") || text.includes("FHD")) return 1080;
    if (text.includes("HD")) return 720;
    if (text.includes("SD")) return 480;
    return 0;
  }

  function renderFpDownloadSources(slug, movie, metadataOnly) {
    const section = byId("fp-detail-sources-section");
    const container = byId("fp-detail-sources");
    container.innerHTML = "";
    const sources = metadataOnly || !Array.isArray(movie.source_providers)
      ? []
      : movie.source_providers.filter((source) => Array.isArray(source.hosters) && source.hosters.length);
    section.hidden = !sources.length;
    if (!sources.length) return;

    const options = [];
    for (const source of sources) {
      const qualities = [...new Set(source.hosters.map((hoster) => String(hoster.quality || "").trim()))];
      qualities.sort((a, b) => movieQualityRank(b) - movieQualityRank(a) || a.localeCompare(b));
      for (const quality of qualities) {
        const matching = source.hosters.filter(
          (hoster) => String(hoster.quality || "").trim() === quality,
        );
        options.push({
          provider: source.key,
          providerLabel: source.label || source.key,
          quality,
          qualityLabel: quality || "Qualität unbekannt",
          hosterCount: matching.length,
          rank: movieQualityRank(quality),
        });
      }
    }
    options.sort((a, b) => b.rank - a.rank);
    const stored = movieState.downloadSelections.get(slug);
    const selected = options.find(
      (option) => option.provider === stored?.provider && option.quality === stored?.quality,
    ) || options[0];
    if (selected) {
      movieState.downloadSelections.set(slug, {
        provider: selected.provider,
        quality: selected.quality,
      });
    }

    for (const option of options) {
      const label = document.createElement("label");
      label.className = "detail-source-option";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `movie-source-${slug}`;
      input.checked = option === selected;
      bind(input, "change", () => {
        movieState.downloadSelections.set(slug, {
          provider: option.provider,
          quality: option.quality,
        });
      });
      const copy = document.createElement("span");
      const provider = document.createElement("strong");
      provider.textContent = option.providerLabel;
      const details = document.createElement("small");
      details.textContent = `${option.qualityLabel} · ${option.hosterCount} Hoster`;
      copy.append(provider, details);
      label.append(input, copy);
      container.appendChild(label);
    }
  }

  function showFpDetail(slug, movie, metadataOnly = false) {
    const detailPanel = byId("fp-detail-panel");
    const cover = byId("fp-detail-cover");
    // Die Abo-Aktion darf nicht von späteren Metadaten-/Hosterfeldern abhängen.
    configureFpSubscriptionAction(slug, movie);
    cover.loading = "eager";
    cover.fetchPriority = "high";
    detailPanel.classList.remove("is-empty");
    detailPanel.classList.toggle("has-no-cover", !movie.cover_url);
    if (movie.cover_url) {
      const posterUrl = coverUrl(movie.cover_url);
      if (cover.getAttribute("src") !== posterUrl) cover.src = posterUrl;
      const backdropUrl = coverUrl(movie.backdrop_url || movie.cover_url).replace(/"/g, "%22");
      detailPanel.style.setProperty("--detail-backdrop-image", `url("${backdropUrl}")`);
    } else if (cover.hasAttribute("src")) {
      cover.removeAttribute("src");
      detailPanel.style.removeProperty("--detail-backdrop-image");
    } else {
      detailPanel.style.removeProperty("--detail-backdrop-image");
    }
    cover.alt = movie.title ? `Poster zu ${movie.title}` : "Filmplakat";
    if (movie.backdrop_url) detailPanel.style.setProperty("--detail-backdrop-image",
      `url("${coverUrl(movie.backdrop_url).replace(/"/g, "%22")}")`);
    byId("fp-detail-title").textContent = movie.title;
    const metaParts = [];
    if (movie.year) metaParts.push(movie.year);
    if (movie.runtime) metaParts.push(movie.runtime);
    if (movie.rating) {
      metaParts.push(
        `★ ${movie.rating}/10${movie.vote_count ? ` · ${formatMovieNumber(movie.vote_count)} Stimmen` : ""}`,
      );
    }
    if (!metadataOnly) {
      if (movie.provider_count) {
        metaParts.push(`${movie.provider_count} Anbieter`);
      }
      metaParts.push(movie.hoster_total
        ? `${movie.hoster_total} Hoster gesamt`
        : (movie.hosters.length ? `${movie.hosters.length} Hoster` : "kein Hoster"));
    }
    if (movie.metadata_source) metaParts.push(movie.metadata_source);
    renderFpDetailItems("fp-detail-meta", metaParts, "Keine Metadaten");
    renderFpDetailItems("fp-detail-genres", movie.genres, "Genre unbekannt");
    const tagline = byId("fp-detail-tagline");
    tagline.textContent = movie.tagline || "";
    tagline.hidden = !movie.tagline;
    setFpDetailJellyfinStatus(fpDetailJellyfinValue(slug, movie));
    if (metadataOnly) setFpDetailAvailability("Streams werden geprüft", "loading");
    else if (movie.hosters.length) {
      setFpDetailAvailability(
        movie.provider_count
          ? `${movie.provider_count} Anbieter · ${movie.hoster_total || movie.hosters.length} Hoster`
          : `${movie.hosters.length} Hoster bereit`,
        "ready",
      );
    }
    else setFpDetailAvailability("Kein Hoster verfügbar", "error");
    setFpDetailText("fp-detail-original-title", movie.original_title);
    setFpDetailText("fp-detail-release", formatMovieDate(movie.release_date));
    setFpDetailText("fp-detail-certification", movieCertificationLabel(movie));
    const languages = (movie.spoken_languages || []).slice(0, 2).join(", ")
      || (movie.original_language ? movie.original_language.toUpperCase() : "");
    const origin = [
      languages,
      ...(movie.countries || []),
    ].filter(Boolean).join(" · ");
    setFpDetailText("fp-detail-origin", origin);
    renderFpAbout(movie);
    const insights = [];
    const status = movieStatusLabel(movie.status);
    const budget = formatMovieMoney(movie.budget);
    const revenue = formatMovieMoney(movie.revenue);
    if (status) insights.push(`Status · ${status}`);
    if (movie.collection) insights.push(`Reihe · ${movie.collection}`);
    if (budget) insights.push(`Budget · ${budget}`);
    if (revenue) insights.push(`Einspiel · ${revenue}`);
    renderFpDetailItems("fp-detail-insights", insights);
    renderFpDetailItems("fp-detail-keywords", movie.keywords || []);
    renderFpSimilarTitles(movie.similar_titles);
    renderFpExtras(movie);
    renderFpCast(movie.cast, movie.tmdb_url);
    renderFpDownloadSources(slug, movie, metadataOnly);
    byId("fp-detail-route-card").classList.toggle("is-loading", metadataOnly);
    setFpDetailText(
      "fp-detail-route",
      metadataOnly ? "Streams werden geprüft" : (movie.provider_route || movie.hoster_route),
    );
    setFpDetailText(
      "fp-detail-score",
      metadataOnly ? "Noch offen" : (movie.hoster_score != null ? String(movie.hoster_score) : ""),
    );
    setFpDetailText(
      "fp-detail-fallback",
      metadataOnly
        ? "Noch offen"
        : (movie.hosters.length
          ? (movie.provider_count
            ? `${movie.provider_fallback_count || 0} Anbieter · ${movie.hoster_fallback_count || 0} Hoster`
            : `${movie.hoster_fallback_count} Alternativen`)
          : ""),
    );
    byId("fp-detail-desc").textContent = movie.description || "(keine Beschreibung)";

    configureFpTrailer(movie);
    configureFpDetailAction(slug, movie, metadataOnly);
    updateTasteFeedbackButtons();
  }

  function mount() {
    if (scope?.active) return;
    scope = createScope(); scope.listen(catalogRoot, "click", dispatch);
  }
  function unmount() { scope?.dispose(); scope = null; }
  function mountDetail() {
    if (detailScope?.active) return;
    detailScope = createScope(); detailScope.listen(detailRoot, "change", dispatch);
    detailScope.listen(byId("fp-detail-subscribe"), "click", openSelectedMovieSubscription);
  }
  function unmountDetail() { detailScope?.dispose(); detailScope = null; }
  return { mount, unmount, mountDetail, unmountDetail, fpStatusMessage, setActiveGenreFilter, mergeCatalogItems, mergeCatalogSources, updateFpInfiniteState, fpResultYear, setFpJellyfinBadge, setFpPosterJellyfinBadge, updateFpJellyfinBadges, fpResultMedia, fpResultAvailability, findFpResultCard, updateFpResultCard, syncFpDetailQueueAction, syncFpQueueIndicators, updateFpResultSelection, renderFpResults, applyFpResults, basicMovieMetadata, metadataPreviewMovie, renderFpDetailItems, setFpDetailAvailability, setFpDetailJellyfinStatus, fpDetailJellyfinValue, formatMovieDate, formatMovieNumber, formatMovieMoney, movieCertificationLabel, movieStatusLabel, setFpDetailText, renderFpCast, configureFpSubscriptionAction, openSelectedMovieSubscription, presentMovieSubscriptions, movieQualityRank, renderFpDownloadSources, showFpDetail };
}
