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
  const pendingSelections = new Map();
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
    if (!series) return false;
    if (["huhu", "serienstream"].includes(series.provider)) return true;
    const capabilities = Array.isArray(series.provider_content_languages)
      ? series.provider_content_languages.filter(Boolean)
      : [];
    return capabilities.length > 1;
  }

  function episodeLanguageChecked(episode) {
    return episode?.language_checked === true
      || episode?.huhu_language_checked === true;
  }

  function episodeLanguageAvailable(episode) {
    return episode?.language_available === true
      || episode?.huhu_language_available === true;
  }

  function episodeHasEnabledStreamLanguage(episode, series = seriesState.current) {
    if (episode?.downloaded || episode?.in_jellyfin) return true;
    const offered = episode?.content_languages || [];
    const enabled = series?.enabled_content_languages?.length
      ? series.enabled_content_languages
      : [...(getEnabledLanguages() || [])];
    if (providerNeedsExactEpisodeLanguage(series)) {
      if (!episodeLanguageChecked(episode)) return false;
      // availability is a snapshot of the profile at probe time. Concrete
      // tracks remain authoritative when the enabled profile changes.
      return offered.length ? offered.some(language => enabled.includes(language)) : episodeLanguageAvailable(episode);
    }
    if (!offered.length) return true;
    return offered.some(language => enabled.includes(language));
  }

  function episodeLanguageLockLabel(episode, series = seriesState.current) {
    if (providerNeedsExactEpisodeLanguage(series) && !episodeLanguageChecked(episode)) return "";
    // Remote source language must never relabel media that is already local.
    if (episode?.downloaded || episode?.in_jellyfin) return "";
    if (episodeHasEnabledStreamLanguage(episode, series)) return "";
    const offered = episode?.content_languages || [];
    if (offered.length === 1) return `NUR ${String(offered[0]).toUpperCase()}`;
    if (providerNeedsExactEpisodeLanguage(series) && episodeLanguageChecked(episode)) {
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
      || (providerNeedsExactEpisodeLanguage(series) && !episodeLanguageChecked(episode))
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

  function pendingDownloadSlugs() {
    return [...pendingSelections].filter(([slug, intent]) => {
      const episode = findCurrentEpisode(slug);
      return intent.generation === seriesState.viewGeneration
        && isEpisodeEligible(episode) && !episodeLanguageChecked(episode);
    }).map(([slug]) => slug);
  }

  function downloadSelectionSlugs() {
    return [...new Set([...seriesState.epPicked, ...pendingDownloadSlugs()])];
  }

  function updateDownloadSelectionControls() {
    const pending = pendingDownloadSlugs().length;
    const count = downloadSelectionSlugs().length;
    byId("series-pick-count").textContent = pending
      ? `${count} ausgewählt · ${pending} prüfen …` : `${count} ausgewählt`;
    byId("series-add-btn").disabled = count === 0 || queuePending;
    byId("series-add-btn").title = pending
      ? "Gesamte Auswahl vormerken · Sprache und Quellen werden im Hintergrund geprüft" : "";
  }

  function tileClass(ep) {
    if (ep.downloaded) return "downloaded";
    if (ep.unreleased) return "scheduled";
    if (isEpisodeQueued(ep)) return "queued";
    if (providerNeedsExactEpisodeLanguage(seriesState.current)
        && !episodeLanguageChecked(ep)
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
    const pending = pendingSelections.get(episode.slug)?.generation === seriesState.viewGeneration
      && !episodeLanguageChecked(episode) && !isEpisodeQueued(episode);
    tile.setAttribute("aria-busy", String(pending));
    tile.classList?.toggle("selection-pending", pending);
    const releaseText = episode.unreleased ? episodeReleaseText(episode) : "";
    const languageLock = isEpisodeQueued(episode) ? "" : episodeLanguageLockLabel(episode, series);
    let languageNotice = tile.querySelector(".ep-language-lock");
    if (languageLock) {
      if (!languageNotice) {
        languageNotice = document.createElement("small");
        languageNotice.className = "ep-language-lock";
        tile.appendChild(languageNotice);
      }
      languageNotice.textContent = languageLock;
    } else languageNotice?.remove();
    tile.setAttribute("aria-label", episode.unreleased
      ? `Folge ${episode.episode}, verfügbar ab ${releaseText}`
      : languageLock ? `Folge ${episode.episode}, ${languageLock} verfügbar, Download gesperrt`
        : `Folge ${episode.episode}`);
    if (isEpisodeQueued(episode)) tile.title = "Vorgemerkt · Sprache und Quellen werden vor dem Download geprüft";
    else if (providerNeedsExactEpisodeLanguage(series) && !episodeLanguageChecked(episode)
        && !episode.downloaded && !episode.in_jellyfin && !episode.unreleased) {
      tile.title = episode.language_check_error
        ? "Sprachprüfung unvollständig · erneut auswählen, um nochmals zu prüfen"
        : "Stream-Sprache wird vor der Auswahl geprüft";
    }
    else if (!episodeHasEnabledStreamLanguage(episode, series)
        && !episode.downloaded && !episode.in_jellyfin && !episode.unreleased) {
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
    else if (episode.source_providers?.some(provider => provider !== series.provider)) {
      tile.title = "Passende Sprache über eine alternative Serienquelle verfügbar";
    } else tile.removeAttribute("title");
    const alternate = episode.source_providers?.some(provider => provider !== series.provider)
      && episodeHasEnabledStreamLanguage(episode, series) && !episode.unreleased && !episode.downloaded && !episode.in_jellyfin;
    let sourceLabel = tile.querySelector(".ep-source-label");
    if (alternate) {
      if (!sourceLabel) { sourceLabel = document.createElement("small"); sourceLabel.className = "ep-source-label"; tile.appendChild(sourceLabel); }
      sourceLabel.textContent = "Ausweichquelle";
    } else sourceLabel?.remove();
  }

  function refreshSeriesTileStates() {
    const series = seriesState.current;
    const container = byId("series-tiles");
    if (!series || !container) return;
    applyPendingSelections();
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
      const pendingCount = season.episodes.filter(ep => pendingSelections.has(ep.slug) && !episodeLanguageChecked(ep)).length;
      button?.setAttribute("aria-busy", String(pendingCount > 0));
      if (count) count.textContent = pendingCount ? `${pickedCount} gewählt · ${pendingCount} prüfen …` : `${pickedCount}/${season.episodes.length} gewählt`;
    }
    const selectableCount = seriesEpisodes(series).filter(
      (episode) => isEpisodeActionable(episode, series)
    ).length;
    updateDownloadSelectionControls();
    byId("series-select-all").disabled = selectableCount === 0;
    byId("series-select-none").disabled = (seriesState.epPicked.size === 0 && pendingSelections.size === 0) || queuePending;
  }

  function renderSeriesTiles() {
    const container = byId("series-tiles");
    container.innerHTML = "";
    const series = seriesState.current;
    if (!series) { byId("series-pick-count").textContent = "0 ausgewählt"; return; }
    applyPendingSelections();
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
      const pendingCount = seasonObj.episodes.filter(ep => pendingSelections.has(ep.slug) && !episodeLanguageChecked(ep)).length;
      seasonBtn.setAttribute("aria-busy", String(pendingCount > 0));
      seasonCount.textContent = pendingCount ? `${pickedCount} gewählt · ${pendingCount} prüfen …` : `${pickedCount}/${seasonObj.episodes.length} gewählt`;
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
        if (ep.unreleased) {
          const release = document.createElement("small");
          release.className = "ep-release";
          release.textContent = releaseText;
          tile.appendChild(release);
        }
        applySeriesEpisodeTileState(tile, ep, series);
        bind(tile, () => toggleEpisodeTile(ep.slug));
        tiles.appendChild(tile);
      }
      row.appendChild(tiles);
      container.appendChild(row);
    }
    updateDownloadSelectionControls();
    byId("series-select-all").disabled = selectableCount === 0;
    byId("series-select-none").disabled = (seriesState.epPicked.size === 0 && pendingSelections.size === 0) || queuePending;
  }

  function applyPendingSelections() {
    for (const [slug, intent] of pendingSelections) {
      if (intent.generation !== seriesState.viewGeneration) {
        pendingSelections.delete(slug);
        continue;
      }
      const episode = findCurrentEpisode(slug);
      if (isEpisodeSelectable(episode)) seriesState.epPicked.add(slug);
    }
  }

  async function selectEpisodes(episodes, select) {
    const series = seriesState.current;
    const generation = seriesState.viewGeneration;
    const intent = { generation };
    const slugs = episodes.map(episode => episode.slug);
    for (const slug of slugs) {
      if (select) pendingSelections.set(slug, intent);
      else { pendingSelections.delete(slug); seriesState.epPicked.delete(slug); }
    }
    // Known episodes react immediately; verified batches join the selection
    // progressively. Pending episodes never become downloadable prematurely.
    renderSeriesTiles();
    if (!select) return;
    try {
      if (providerNeedsExactEpisodeLanguage(series)) await verifyHuhuEpisodeLanguages(episodes, series);
      if (generation === seriesState.viewGeneration && slugs.some(slug => pendingSelections.get(slug) === intent)) {
        status.textContent = `${seriesState.epPicked.size} Folge(n) ausgewählt.`;
      }
    } catch (error) {
      if (error.name !== "AbortError" && generation === seriesState.viewGeneration) {
        status.textContent = `Stream-Sprachen konnten nicht geprüft werden: ${error.message}`;
      }
    } finally {
      if (generation === seriesState.viewGeneration && seriesState.current?.base_slug === series.base_slug
          && seriesState.current?.provider === series.provider) {
        applyPendingSelections();
        for (const slug of slugs) if (pendingSelections.get(slug) === intent) pendingSelections.delete(slug);
        renderSeriesTiles();
      }
    }
  }

  function toggleEpisodeTile(slug) {
    const episode = findCurrentEpisode(slug);
    if (!isEpisodeActionable(episode)) return;
    return selectEpisodes([episode], !seriesState.epPicked.has(slug) && !pendingSelections.has(slug));
  }

  function toggleSeasonTiles(season) {
    const seasonObj = seriesState.current?.seasons.find(s => s.season === season);
    if (!seasonObj) return;
    const eligible = seasonObj.episodes.filter(episode => isEpisodeActionable(episode));
    if (!eligible.length) return;
    const allPicked = eligible.every(episode => seriesState.epPicked.has(episode.slug) || pendingSelections.has(episode.slug));
    return selectEpisodes(eligible, !allPicked);
  }

  function selectAllSeriesEpisodes() {
    return selectEpisodes(seriesEpisodes().filter(episode => isEpisodeActionable(episode)), true);
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
    const current = () => owner.active && seriesState.viewGeneration === generation && !root.hidden
      && (seriesState.current === series || (series?.base_slug
        && seriesState.current?.base_slug === series.base_slug && seriesState.current?.provider === series.provider));
    pruneSeriesEpisodeSelection();
    const slugs = downloadSelectionSlugs();
    const submittedIntents = new Map(slugs.map(slug => [slug, pendingSelections.get(slug)]));
    const pendingCount = pendingDownloadSlugs().length;
    if (!slugs.length) {
      byId("series-status").textContent =
        "Keine herunterladbaren Episoden ausgewählt.";
      renderSeriesTiles();
      return;
    }
    queuePending = true;
    byId("series-status").textContent = `Merke ${slugs.length} Episode(n) vor …`;
    const addButton = byId("series-add-btn");
    addButton.disabled = true;
    try {
      const resp = await client.post("/api/queue/add", { slugs, preferences: {}, source: "web" }, { signal: owner.signal });
      if (!owner.active) return;
      if (Number(resp.added || 0) > 0 && series) {
        trackDiscoveryPreference("series", series, 5, "download");
      }
      if (current()) {
        for (const slug of slugs) {
          // Consume only this click's selection. A later batch must not
          // reselect an already submitted episode or consume newer intent.
          if (!pendingSelections.has(slug) || pendingSelections.get(slug) === submittedIntents.get(slug)) {
            pendingSelections.delete(slug);
            seriesState.epPicked.delete(slug);
          }
        }
      }
      refreshQueueUiAfterChange(resp);
      if (!current()) return;
      byId("series-status").textContent =
        `${resp.added}/${slugs.length} Episode(n) vorgemerkt${pendingCount
          ? " · Sprache und Quellen werden im Hintergrund geprüft" : " · Downloads starten automatisch"}`;
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
    scope.listen(byId("series-select-none"), "click", () => { pendingSelections.clear(); seriesState.epPicked.clear(); renderSeriesTiles(); });
    scope.listen(byId("series-add-btn"), "click", seriesAddSelected);
  }
  function unmount() { scope.dispose(); pendingSelections.clear(); bound = false; queuePending = false; }
  return { mount, unmount, firstEpisodeSlug, seriesEpisodes, isEpisodeQueued, episodeHasEnabledStreamLanguage, episodeLanguageLockLabel, isEpisodeEligible, isEpisodeSelectable, isEpisodeActionable, syncSeriesQueueFlags, pruneSeriesEpisodeSelection, findCurrentEpisode, tileClass, episodeReleaseText, seriesAvailabilityNotice, syncSeriesAvailabilityNotice, applySeriesEpisodeTileState, refreshSeriesTileStates, renderSeriesTiles, toggleEpisodeTile, toggleSeasonTiles, selectAllSeriesEpisodes, markSeriesSlugDownloaded, seriesAddSelected };
}
