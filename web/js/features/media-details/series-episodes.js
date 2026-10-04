import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Episode eligibility, selection and queue commands share the series detail lifecycle. */
export function createSeriesEpisodes(root, {
  status, seriesState, getQueuedSlugs, isQueueLoaded = () => false, getEnabledLanguages, verifyHuhuEpisodeLanguages,
  trackDiscoveryPreference, refreshQueueUiAfterChange, client = api,
}) {
  const document = root.ownerDocument;
  const byId = id => id === "series-status" ? status : root.querySelector(`#${id}`);
  const actions = new WeakMap();
  let scope = createScope(), bound = false, queuePending = false;
  const bind = (node, action) => actions.set(node, action);
  function firstEpisodeSlug(series) {
    for (const s of series.seasons) if (s.episodes.length) return s.episodes[0].slug;
    return "";
  }

  function seriesEpisodes(series = seriesState.current) {
    return series?.seasons?.flatMap((season) => season.episodes || []) || [];
  }

  function isEpisodeQueued(episode) {
    return Boolean(episode?.queued || getQueuedSlugs().has(episode?.slug));
  }

  function providerNeedsExactEpisodeLanguage(series = seriesState.current) {
    return ["huhu", "serienstream"].includes(series?.provider);
  }

  function episodeHasEnabledStreamLanguage(episode, series = seriesState.current) {
    if (episode?.downloaded || episode?.in_jellyfin) return true;
    if (providerNeedsExactEpisodeLanguage(series)) {
      if (episode?.language_checked !== true) return true;
      return episode?.language_available === true;
    }
    const offered = episode?.content_languages || [];
    if (!offered.length) return true;
    const enabled = series?.enabled_content_languages?.length
      ? series.enabled_content_languages
      : [...(getEnabledLanguages() || [])];
    return offered.some((language) => enabled.includes(language));
  }

  function episodeLanguageLockLabel(episode, series = seriesState.current) {
    // Remote source language must never relabel media that is already local.
    if (episode?.downloaded || episode?.in_jellyfin) return "";
    if (episodeHasEnabledStreamLanguage(episode, series)) return "";
    const offered = episode?.content_languages || [];
    if (offered.length === 1) return `NUR ${String(offered[0]).toUpperCase()}`;
    if (providerNeedsExactEpisodeLanguage(series) && episode?.language_checked) {
      return "KEINE PASSENDE SPRACHE";
    }
    return offered.length ? "SPRACHE GESPERRT" : "";
  }

  function isEpisodeEligible(episode) {
    return Boolean(
      episode
      && !episode.downloaded
      && !episode.in_jellyfin
      && !episode.unreleased
      && !isEpisodeQueued(episode)
    );
  }

  function isEpisodeSelectable(episode) {
    return Boolean(
      episode
      && !episode.downloaded
      && !episode.in_jellyfin
      && !episode.unreleased
      && !isEpisodeQueued(episode)
      && episodeHasEnabledStreamLanguage(episode, seriesState.current)
    );
  }

  function isEpisodeActionable(episode, series = seriesState.current) {
    return isEpisodeEligible(episode) && (
      isEpisodeSelectable(episode)
      || (providerNeedsExactEpisodeLanguage(series) && !episode.language_checked)
    );
  }

  function syncSeriesQueueFlags(series = null) {
    const candidates = series
      ? [series]
      : [seriesState.current, ...Object.values(seriesState.cache)];
    const visited = new Set();
    for (const candidate of candidates) {
      if (!candidate || visited.has(candidate)) continue;
      visited.add(candidate);
      if (isQueueLoaded()) {
        for (const episode of seriesEpisodes(candidate)) {
          episode.queued = getQueuedSlugs().has(episode.slug);
        }
      }
    }
    if (!series || series === seriesState.current) {
      pruneSeriesEpisodeSelection();
      renderSeriesTiles();
    }
  }

  function pruneSeriesEpisodeSelection() {
    const selectableSlugs = new Set(
      seriesEpisodes().filter(isEpisodeSelectable).map((episode) => episode.slug),
    );
    seriesState.epPicked = new Set(
      [...seriesState.epPicked].filter((slug) => selectableSlugs.has(slug)),
    );
  }

  function findCurrentEpisode(slug) {
    return seriesEpisodes().find((episode) => episode.slug === slug) || null;
  }

  function tileClass(ep) {
    if (isEpisodeQueued(ep)) return "queued";
    if (ep.downloaded) return "downloaded";
    if (ep.unreleased) return "scheduled";
    if (providerNeedsExactEpisodeLanguage(seriesState.current)
        && !ep.language_checked
        && !ep.downloaded
        && !ep.in_jellyfin) {
      return "language-pending";
    }
    if (!episodeHasEnabledStreamLanguage(ep)) return "wrong-language";
    if (seriesState.epPicked.has(ep.slug) && isEpisodeSelectable(ep)) return "selected";
    return "available";
  }

  function episodeReleaseText(ep) {
    const release = new Date(ep?.release_at || "");
    if (!Number.isNaN(release.getTime())) {
      return new Intl.DateTimeFormat("de-DE", {
        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      }).format(release).replace(",", " ·").toLocaleUpperCase("de-DE");
    }
    return ep?.release_label || "DEMNÄCHST";
  }

  function seriesAvailabilityNotice(series) {
    if (series.availability_pending) {
      return series.availability_error
        ? "Verfügbarkeitsprüfung fehlgeschlagen · Auswahl und Download bleiben möglich."
        : "Staffeln sind da · Bestand und Metadaten werden im Hintergrund geprüft …";
    }
    if (series.jellyfin_available === false) {
      return "Jellyfin konnte nicht eindeutig abgeglichen werden · Auswahl und Download bleiben möglich.";
    }
    return "";
  }

  function syncSeriesAvailabilityNotice(container, series) {
    let notice = container.querySelector(":scope > .series-loading");
    const text = seriesAvailabilityNotice(series);
    if (!text) {
      notice?.remove();
      return;
    }
    if (!notice) {
      notice = document.createElement("div");
      notice.className = "series-loading";
      container.prepend(notice);
    }
    if (notice.textContent !== text) notice.textContent = text;
  }

  function applySeriesEpisodeTileState(tile, episode, series) {
    tile.className = "ep-tile " + tileClass(episode) + (episode.in_jellyfin ? " in-jellyfin" : "");
    tile.disabled = !isEpisodeActionable(episode, series);
    const releaseText = episode.unreleased ? episodeReleaseText(episode) : "";
    const languageLock = episodeLanguageLockLabel(episode, series);
    if (providerNeedsExactEpisodeLanguage(series) && !episode.language_checked
        && isEpisodeEligible(episode)) {
      tile.title = "Stream-Sprache wird vor der Auswahl geprüft";
    }
    else if (!episodeHasEnabledStreamLanguage(episode, series)
        && isEpisodeEligible(episode)) {
      tile.title = languageLock === "NUR EN"
        ? "Nur auf Englisch verfügbar · Download mit deutscher Sprachwahl gesperrt"
        : "Keine Episode in den aktivierten Stream-Sprachen verfügbar";
    }
    else if (series.availability_error) tile.title = "Verfügbarkeitsprüfung fehlgeschlagen";
    else if (series.availability_pending) tile.title = "Verfügbarkeit wird geprüft";
    else if (episode.in_jellyfin) tile.title = "Bereits in Jellyfin vorhanden";
    else if (episode.downloaded) tile.title = "Bereits heruntergeladen";
    else if (isEpisodeQueued(episode)) tile.title = "Bereits in der Warteschlange";
    else if (episode.unreleased) tile.title = `Download gesperrt · verfügbar ab ${releaseText}`;
    else tile.removeAttribute("title");
  }

  function refreshSeriesTileStates() {
    const series = seriesState.current;
    const container = byId("series-tiles");
    if (!series || !container) return;
    syncSeriesAvailabilityNotice(container, series);
    const episodesBySlug = new Map(seriesEpisodes(series).map((episode) => [episode.slug, episode]));
    for (const tile of container.querySelectorAll(".ep-tile[data-episode-slug]")) {
      const episode = episodesBySlug.get(tile.dataset.episodeSlug);
      if (episode) applySeriesEpisodeTileState(tile, episode, series);
    }
    for (const season of series.seasons || []) {
      const row = [...container.querySelectorAll(".season-row")]
        .find((candidate) => Number(candidate.dataset.season) === Number(season.season));
      if (!row) continue;
      const pickedCount = season.episodes.filter((episode) => seriesState.epPicked.has(episode.slug)).length;
      const button = row.querySelector(".season-btn");
      const count = button?.querySelector("small");
      if (button) button.disabled = !season.episodes.some(
        (episode) => isEpisodeActionable(episode, series)
      );
      if (count) count.textContent = `${pickedCount}/${season.episodes.length} gewählt`;
    }
    const selectableCount = seriesEpisodes(series).filter(
      (episode) => isEpisodeActionable(episode, series)
    ).length;
    byId("series-pick-count").textContent = `${seriesState.epPicked.size} ausgewählt`;
    byId("series-select-all").disabled = selectableCount === 0;
    byId("series-select-none").disabled = seriesState.epPicked.size === 0 || queuePending;
    byId("series-add-btn").disabled = seriesState.epPicked.size === 0 || queuePending;
  }

  function renderSeriesTiles() {
    const container = byId("series-tiles");
    container.innerHTML = "";
    const series = seriesState.current;
    if (!series) { byId("series-pick-count").textContent = "0 ausgewählt"; return; }
    pruneSeriesEpisodeSelection();
    syncSeriesAvailabilityNotice(container, series);
    const selectableCount = seriesEpisodes(series).filter(
      (episode) => isEpisodeActionable(episode, series)
    ).length;
    for (const seasonObj of series.seasons) {
      const pickedCount = seasonObj.episodes.filter((e) => seriesState.epPicked.has(e.slug)).length;
      const row = document.createElement("div");
      row.className = "season-row";
      row.dataset.season = seasonObj.season;
      const seasonBtn = document.createElement("button");
      seasonBtn.className = "season-btn";
      seasonBtn.setAttribute("aria-label", `Staffel ${seasonObj.season}: ${pickedCount} von ${seasonObj.episodes.length} ausgewählt`);
      const seasonLabel = document.createElement("span");
      seasonLabel.textContent = "STAFFEL";
      const seasonNumber = document.createElement("strong");
      seasonNumber.textContent = String(seasonObj.season).padStart(2, "0");
      const seasonCount = document.createElement("small");
      seasonCount.textContent = `${pickedCount}/${seasonObj.episodes.length} gewählt`;
      seasonBtn.append(seasonLabel, seasonNumber, seasonCount);
      seasonBtn.disabled = !seasonObj.episodes.some(
        (episode) => isEpisodeActionable(episode, series)
      );
      bind(seasonBtn, () => toggleSeasonTiles(seasonObj.season));
      row.appendChild(seasonBtn);
      const tiles = document.createElement("div");
      tiles.className = "ep-tiles";
      for (const ep of seasonObj.episodes) {
        const tile = document.createElement("button");
        tile.dataset.episodeSlug = ep.slug;
        applySeriesEpisodeTileState(tile, ep, series);
        const releaseText = ep.unreleased ? episodeReleaseText(ep) : "";
        const languageLock = episodeLanguageLockLabel(ep, series);
        tile.setAttribute(
          "aria-label",
          ep.unreleased ? `Folge ${ep.episode}, verfügbar ab ${releaseText}`
            : languageLock ? `Folge ${ep.episode}, ${languageLock} verfügbar, Download gesperrt`
              : `Folge ${ep.episode}`,
        );
        const episodeLabel = document.createElement("span");
        episodeLabel.textContent = "FOLGE";
        const episodeNumber = document.createElement("strong");
        episodeNumber.textContent = String(ep.episode).padStart(2, "0");
        tile.append(episodeLabel, episodeNumber);
        if (languageLock) {
          const languageNotice = document.createElement("small");
          languageNotice.className = "ep-language-lock";
          languageNotice.textContent = languageLock;
          tile.appendChild(languageNotice);
        }
        if (ep.unreleased) {
          const release = document.createElement("small");
          release.className = "ep-release";
          release.textContent = releaseText;
          tile.appendChild(release);
        }
        bind(tile, () => toggleEpisodeTile(ep.slug));
        tiles.appendChild(tile);
      }
      row.appendChild(tiles);
      container.appendChild(row);
    }
    byId("series-pick-count").textContent = `${seriesState.epPicked.size} ausgewählt`;
    byId("series-select-all").disabled = selectableCount === 0;
    byId("series-select-none").disabled = seriesState.epPicked.size === 0 || queuePending;
    byId("series-add-btn").disabled = seriesState.epPicked.size === 0 || queuePending;
  }

  async function toggleEpisodeTile(slug) {
    const episode = findCurrentEpisode(slug);
    const series = seriesState.current;
    if (isEpisodeEligible(episode) && providerNeedsExactEpisodeLanguage(series)) {
      try {
        await verifyHuhuEpisodeLanguages([episode], series);
      } catch (error) {
        if (error.name === "AbortError") return;
        byId("series-status").textContent =
          `Deutsche Quelle konnte nicht geprüft werden: ${error.message}`;
        return;
      }
      if (seriesState.current !== series) return;
    }
    if (!isEpisodeSelectable(episode)) {
      seriesState.epPicked.delete(slug);
      renderSeriesTiles();
      return;
    }
    if (seriesState.epPicked.has(slug)) seriesState.epPicked.delete(slug);
    else seriesState.epPicked.add(slug);
    renderSeriesTiles();
  }

  async function toggleSeasonTiles(season) {
    const series = seriesState.current;
    const seasonObj = series.seasons.find((s) => s.season === season);
    if (!seasonObj) return;
    const eligible = seasonObj.episodes.filter(isEpisodeEligible);
    if (!eligible.length) return;
    const generation = seriesState.viewGeneration;
    if (providerNeedsExactEpisodeLanguage(series)) {
      try {
        await verifyHuhuEpisodeLanguages(eligible, series);
      } catch (error) {
        if (error.name === "AbortError") return;
        byId("series-status").textContent =
          `Deutsche Quellen konnten nicht geprüft werden: ${error.message}`;
        return;
      }
      if (seriesState.current !== series || seriesState.viewGeneration !== generation) return;
    }
    const selectable = seasonObj.episodes.filter(isEpisodeSelectable);
    if (!selectable.length) return;
    const allPicked = selectable.every((episode) => seriesState.epPicked.has(episode.slug));
    for (const ep of seasonObj.episodes) {
      if (!isEpisodeSelectable(ep) || allPicked) seriesState.epPicked.delete(ep.slug);
      else seriesState.epPicked.add(ep.slug);
    }
    renderSeriesTiles();
  }

  async function selectAllSeriesEpisodes() {
    const series = seriesState.current;
    if (!series) return;
    if (providerNeedsExactEpisodeLanguage(series)) {
      try {
        await verifyHuhuEpisodeLanguages(seriesEpisodes(series).filter(isEpisodeEligible), series);
      } catch (error) {
        if (error.name === "AbortError") return;
        byId("series-status").textContent =
          `Deutsche Quellen konnten nicht geprüft werden: ${error.message}`;
        return;
      }
      if (seriesState.current !== series) return;
    }
    seriesState.epPicked = new Set(
      seriesEpisodes(series).filter(isEpisodeSelectable).map((episode) => episode.slug),
    );
    renderSeriesTiles();
  }

  function markSeriesSlugDownloaded(slug) {
    const series = seriesState.current;
    if (!series) return;
    for (const s of series.seasons) {
      for (const ep of s.episodes) {
        if (ep.slug === slug) { ep.downloaded = true; refreshSeriesTileStates(); return; }
      }
    }
  }

  async function seriesAddSelected() {
    if (!scope.active || queuePending) return;
    const owner = scope, series = seriesState.current, generation = seriesState.viewGeneration;
    const current = () => owner.active && seriesState.current === series && seriesState.viewGeneration === generation && !root.hidden;
    pruneSeriesEpisodeSelection();
    if (!seriesState.epPicked.size) {
      byId("series-status").textContent =
        "Keine herunterladbaren Episoden ausgewählt.";
      renderSeriesTiles();
      return;
    }
    queuePending = true;
    const slugs = [...seriesState.epPicked];
    byId("series-status").textContent = `Lade ${slugs.length} Episode(n) …`;
    const addButton = byId("series-add-btn");
    addButton.disabled = true;
    try {
      const resp = await client.post("/api/queue/add", { slugs, preferences: {}, source: "web" }, { signal: owner.signal });
      if (!owner.active) return;
      if (Number(resp.added || 0) > 0 && series) {
        trackDiscoveryPreference("series", series, 5, "download");
      }
      refreshQueueUiAfterChange(resp);
      if (!current()) return;
      byId("series-status").textContent =
        `${resp.added}/${slugs.length} Episode(n) automatisch gestartet`;
      seriesState.epPicked.clear();
    } catch (error) {
      if (!current()) return;
      byId("series-status").textContent =
        `Download konnte nicht gestartet werden: ${error.message}`;
    } finally {
      if (owner.active) { queuePending = false; renderSeriesTiles(); }
    }
  }

  function mount() {
    if (bound) return;
    if (!scope.active) scope = createScope();
    bound = true;
    scope.listen(root, "click", event => {
      for (let node = event.target; node && node !== root; node = node.parentElement) {
        const action = actions.get(node);
        if (action) { void action(); return; }
      }
    });
    scope.listen(byId("series-select-all"), "click", selectAllSeriesEpisodes);
    scope.listen(byId("series-select-none"), "click", () => { seriesState.epPicked.clear(); renderSeriesTiles(); });
    scope.listen(byId("series-add-btn"), "click", seriesAddSelected);
  }
  function unmount() { scope.dispose(); bound = false; queuePending = false; }
  return { mount, unmount, firstEpisodeSlug, seriesEpisodes, isEpisodeQueued, episodeHasEnabledStreamLanguage, episodeLanguageLockLabel, isEpisodeEligible, isEpisodeSelectable, isEpisodeActionable, syncSeriesQueueFlags, pruneSeriesEpisodeSelection, findCurrentEpisode, tileClass, episodeReleaseText, seriesAvailabilityNotice, syncSeriesAvailabilityNotice, applySeriesEpisodeTileState, refreshSeriesTileStates, renderSeriesTiles, toggleEpisodeTile, toggleSeasonTiles, selectAllSeriesEpisodes, markSeriesSlugDownloaded, seriesAddSelected };
}
