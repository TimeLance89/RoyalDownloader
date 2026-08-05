// ── Init ─────────────────────────────────────────────────────────────────
async function initApp() {
  await i18n.initialize();
  initLoginScreen();
  // Blockiert, bis eine gültige Sitzung besteht. Ohne eingerichtetes Konto
  // oder vor der Ersteinrichtung kehrt der Aufruf sofort zurück.
  await requireLogin();
  document.querySelectorAll(".media-modal").forEach((modal) => document.body.appendChild(modal));
  buildAlphaBar();
  connectWs();
  initSettingsNavigation();
  initCatalogInfiniteScroll();

  document.querySelectorAll(".tab-btn[data-tab]").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

  document.getElementById("mobile-queue-btn").addEventListener("click", openMobileQueue);
  document.getElementById("mobile-queue-close").addEventListener("click", closeMobileQueue);
  document.getElementById("mobile-queue-backdrop").addEventListener("click", closeMobileQueue);
  document.getElementById("queue-dock-toggle").addEventListener("click", toggleDesktopQueue);
  document.querySelectorAll("[data-modal-close]").forEach((button) => {
    button.addEventListener("click", () => closeMediaModal(button.dataset.modalClose));
  });
  document.getElementById("fp-taste-like").addEventListener("click", () => setTasteFeedback("movie", "like"));
  document.getElementById("fp-taste-dislike").addEventListener("click", () => setTasteFeedback("movie", "dislike"));
  document.getElementById("series-taste-like").addEventListener("click", () => setTasteFeedback("series", "like"));
  document.getElementById("series-taste-dislike").addEventListener("click", () => setTasteFeedback("series", "dislike"));

  // Startseite
  document.getElementById("home-hero-open").addEventListener("click", (event) => {
    const { kind, key } = event.currentTarget.dataset;
    if (kind && key) openHomeEntry(kind, key);
  });
  document.getElementById("home-hero-list").addEventListener("click", () => switchTab("bibliothek"));
  document.getElementById("home-discovery-shuffle").addEventListener("click", shuffleHomeDiscovery);
  document.querySelectorAll("[data-mood-open]").forEach((button) => {
    button.addEventListener("click", () => openMoodMatch(button));
  });
  document.querySelectorAll("[data-mood-close]").forEach((button) => {
    button.addEventListener("click", () => closeMoodMatch());
  });
  document.getElementById("mood-back").addEventListener("click", moodMatchBack);
  document.getElementById("mood-next").addEventListener("click", moodMatchNext);
  document.getElementById("mood-modal").addEventListener("keydown", handleMoodMatchKeydown);
  document.getElementById("home-hero-prev").addEventListener("click", () => {
    showHomeHero(state.home.heroIndex - 1, true);
    scheduleHomeHeroRotation();
  });
  document.getElementById("home-hero-next").addEventListener("click", () => {
    showHomeHero(state.home.heroIndex + 1, true);
    scheduleHomeHeroRotation();
  });
  const homeHero = document.getElementById("home-hero");
  homeHero.addEventListener("pointerenter", stopHomeHeroRotation);
  homeHero.addEventListener("pointerleave", scheduleHomeHeroRotation);
  homeHero.addEventListener("focusin", stopHomeHeroRotation);
  homeHero.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!homeHero.contains(document.activeElement)) scheduleHomeHeroRotation();
    }, 0);
  });
  document.querySelectorAll("[data-home-scroll]").forEach((button) => {
    button.addEventListener("click", () => {
      const track = document.getElementById(button.dataset.homeScroll);
      const direction = Number(button.dataset.direction) || 1;
      track?.scrollBy({ left: direction * Math.max(280, track.clientWidth * 0.82), behavior: "smooth" });
    });
  });
  document.querySelectorAll("#tab-home .home-track").forEach((track) => {
    let navigationFrame = 0;
    track.addEventListener("scroll", () => {
      cancelAnimationFrame(navigationFrame);
      navigationFrame = requestAnimationFrame(() => updateHomeRailNavigation(track));
    }, { passive: true });
    updateHomeRailNavigation(track);
  });
  window.addEventListener("resize", () => {
    document.querySelectorAll("#tab-home .home-track").forEach(updateHomeRailNavigation);
  });
  const globalSearchInput = document.getElementById("global-search-input");
  const globalSearchToggle = document.getElementById("global-search-toggle");
  const globalSearchPage = document.getElementById("global-search-page");
  globalSearchToggle.addEventListener("click", openGlobalSearch);
  globalSearchInput.addEventListener("focus", () => {
    document.getElementById("global-search-shell").classList.add("is-expanded");
    globalSearchToggle.setAttribute("aria-expanded", "true");
  });
  globalSearchInput.addEventListener("blur", () => {
    window.setTimeout(() => {
      if (globalSearchInput.value || document.getElementById("global-search-shell").contains(document.activeElement)) return;
      document.getElementById("global-search-shell").classList.remove("is-expanded");
      globalSearchToggle.setAttribute("aria-expanded", "false");
    }, 0);
  });
  globalSearchInput.addEventListener("input", syncGlobalSearchDraft);
  globalSearchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runGlobalSearch();
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeGlobalSearch({ restoreFocus: true });
      document.getElementById("global-search-shell").classList.remove("is-expanded");
    }
  });
  document.getElementById("global-search-clear").addEventListener("click", () => {
    closeGlobalSearch({ restoreFocus: true });
    document.getElementById("global-search-shell").classList.remove("is-expanded");
  });
  document.querySelectorAll("[data-global-search-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      state.globalSearch.scope = button.dataset.globalSearchScope;
      renderGlobalSearchResults();
    });
  });
  document.getElementById("global-search-jellyfin").addEventListener("click", () => {
    state.globalSearch.jellyfinOnly = !state.globalSearch.jellyfinOnly;
    renderGlobalSearchResults();
  });
  globalSearchPage.addEventListener("click", (event) => {
    if (event.target.closest(".global-search-head, .home-card")) return;
    closeGlobalSearch();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!state.globalSearch.active) return;
    if (document.getElementById("global-search-shell").contains(event.target)) return;
    if (globalSearchPage.contains(event.target)) return;
    closeGlobalSearch();
  });
  document.getElementById("home-search-btn").addEventListener("click", homeSearch);
  document.getElementById("home-search-close").addEventListener("click", closeHomeSearch);
  document.getElementById("home-search-clear").addEventListener("click", closeHomeSearch);
  document.getElementById("home-search").addEventListener("input", () => {
    syncSearchClearButtons();
    closeSearchSuggestions("home-search-suggestions", "home-search");
  });
  document.getElementById("home-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      homeSearch();
    } else if (event.key === "Escape") {
      event.stopPropagation();
      closeSearchSuggestions("home-search-suggestions", "home-search");
    }
  });
  window.setInterval(() => {
    if (state.tab !== "home" || state.home.discoveryDay === localDateKey()) return;
    state.home.heroIndex = 0;
    renderHome();
  }, 5 * 60 * 1000);
  document.querySelectorAll("[data-home-search-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      state.home.search.scope = button.dataset.homeSearchScope;
      document.querySelectorAll("[data-home-search-scope]").forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("is-active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
    });
  });

  // Filme
  document.getElementById("fp-search-btn").addEventListener("click", fpSearch);
  document.getElementById("fp-search-clear").addEventListener("click", async () => {
    document.getElementById("fp-search").value = "";
    syncSearchClearButtons();
    closeSearchSuggestions("fp-search-suggestions", "fp-search");
    await restoreFpSearchContext();
  });
  document.getElementById("fp-search").addEventListener("input", () => {
    syncSearchClearButtons();
    closeSearchSuggestions("fp-search-suggestions", "fp-search");
  });
  document.getElementById("fp-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      fpSearch();
    } else if (event.key === "Escape") {
      event.stopPropagation();
      closeSearchSuggestions("fp-search-suggestions", "fp-search");
    }
  });
  document.getElementById("fp-search").addEventListener("blur", (event) => {
    if (!event.currentTarget.value.trim()) restoreFpSearchContext();
  });
  document.getElementById("fp-new-btn").addEventListener("click", () => fpShowList("new"));
  document.getElementById("fp-top-btn").addEventListener("click", () => fpShowList("top"));
  document.getElementById("fp-trailer-close").addEventListener("click", () => {
    closeFpTrailerModal();
  });
  document.getElementById("fp-trailer-backdrop").addEventListener("click", () => {
    closeFpTrailerModal();
  });
  document.getElementById("fp-detail-hero-mute").addEventListener("click", () => {
    setFpDetailHeroTrailerMuted(!fpDetailHeroTrailerMuted, { persist: true });
  });
  document.getElementById("series-detail-hero-mute").addEventListener("click", () => {
    setFpDetailHeroTrailerMuted(!fpDetailHeroTrailerMuted, { persist: true });
  });
  document.getElementById("movie-feature-open").addEventListener("click", (event) => {
    const slug = event.currentTarget.dataset.slug;
    if (slug) selectFpRow(slug);
  });
  document.getElementById("movie-feature-prev").addEventListener("click", () => {
    showMovieFeature(state.fp.featureIndex - 1, true);
    scheduleMovieFeatureRotation();
  });
  document.getElementById("movie-feature-next").addEventListener("click", () => {
    showMovieFeature(state.fp.featureIndex + 1, true);
    scheduleMovieFeatureRotation();
  });
  document.getElementById("movie-feature-pause").addEventListener("click", () => {
    setMovieFeaturePaused(!state.fp.featurePaused);
  });
  const movieFeature = document.getElementById("movie-feature");
  movieFeature.addEventListener("pointerenter", stopMovieFeatureRotation);
  movieFeature.addEventListener("pointerleave", scheduleMovieFeatureRotation);
  movieFeature.addEventListener("focusin", stopMovieFeatureRotation);
  movieFeature.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!movieFeature.contains(document.activeElement)) scheduleMovieFeatureRotation();
    }, 0);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopMovieFeatureRotation();
      stopHomeHeroRotation();
    } else {
      scheduleMovieFeatureRotation();
      scheduleHomeHeroRotation();
    }
  });
  document.getElementById("genre-filter").addEventListener("click", (e) => {
    const button = e.target.closest("[data-genre]");
    if (button) fpGenreChange(button.dataset.genre);
  });
  document.getElementById("genre-toggle").addEventListener("click", (e) => {
    const filter = document.getElementById("genre-filter");
    const expanded = filter.classList.toggle("is-expanded");
    e.currentTarget.setAttribute("aria-expanded", String(expanded));
    e.currentTarget.querySelector(".genre-toggle-label").textContent = expanded ? "Weniger zeigen" : "Alle zeigen";
  });
  document.getElementById("genre-random").addEventListener("click", () => {
    const genres = [...document.querySelectorAll("#genre-filter [data-genre]")]
      .map((button) => button.dataset.genre)
      .filter((genre) => genre !== "Alle Genres" && genre !== state.fp.activeGenre);
    if (!genres.length) return;
    fpGenreChange(genres[Math.floor(Math.random() * genres.length)]);
  });
  document.getElementById("movie-subscriptions-check").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Prüfe …";
    try {
      const response = await api.movieSubscriptionsCheck();
      applyMovieSubscriptions(response.movie_subscriptions || []);
    } finally {
      button.textContent = "↻ Qualitäten prüfen";
      button.disabled = !state.movieSubscriptions.items.length;
    }
  });
  document.getElementById("fp-detail-subscribe").addEventListener("click", openSelectedMovieSubscription);
  document.getElementById("movie-subscription-close").addEventListener("click", closeMovieSubscriptionModal);
  document.getElementById("movie-subscription-cancel").addEventListener("click", closeMovieSubscriptionModal);
  document.getElementById("movie-subscription-save").addEventListener("click", saveMovieSubscription);
  document.getElementById("movie-subscription-remove").addEventListener("click", removeMovieSubscription);
  document.getElementById("movie-subscription-modal").addEventListener("click", (event) => {
    if (event.target.id === "movie-subscription-modal") closeMovieSubscriptionModal();
  });
  document.querySelectorAll('input[name="movie-cleanup"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const status = document.getElementById("movie-subscription-status");
      status.textContent = !state.jellyfinUserConfigured && radio.checked && radio.value === "watched"
        ? "Für die Gesehen-Löschung muss unter Einstellungen ein Jellyfin-Profil gewählt sein."
        : "";
    });
  });
  // Serien
  document.getElementById("series-search-btn").addEventListener("click", seriesSearch);
  document.getElementById("series-search-clear").addEventListener("click", async () => {
    document.getElementById("series-search").value = "";
    syncSearchClearButtons();
    closeSearchSuggestions("series-search-suggestions", "series-search");
    await restoreSeriesSearchContext();
  });
  document.getElementById("series-search").addEventListener("input", () => {
    syncSearchClearButtons();
    closeSearchSuggestions("series-search-suggestions", "series-search");
  });
  document.getElementById("series-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      seriesSearch();
    } else if (event.key === "Escape") {
      event.stopPropagation();
      closeSearchSuggestions("series-search-suggestions", "series-search");
    }
  });
  document.getElementById("series-search").addEventListener("blur", (event) => {
    if (!event.currentTarget.value.trim()) restoreSeriesSearchContext();
  });
  document.getElementById("series-discover-btn").addEventListener("click", () => seriesBrowse("discover", 1));
  document.getElementById("series-new-btn").addEventListener("click", () => seriesBrowse("new", 1));
  document.getElementById("series-trending-btn").addEventListener("click", () => seriesBrowse("trending", 1));
  document.getElementById("series-az-btn").addEventListener("click", () => {
    document.getElementById("series-alpha-bar").classList.toggle("hidden");
  });
  document.getElementById("series-select-all").addEventListener("click", () => {
    if (!state.series.current) return;
    state.series.epPicked = new Set(
      seriesEpisodes().filter(isEpisodeSelectable).map((episode) => episode.slug),
    );
    renderSeriesTiles();
  });
  document.getElementById("series-select-none").addEventListener("click", () => {
    state.series.epPicked.clear();
    renderSeriesTiles();
  });
  document.getElementById("series-add-btn").addEventListener("click", seriesAddSelected);
  document.getElementById("series-watch-btn").addEventListener("click", () => openWatchModeModal());
  document.getElementById("series-subscriptions-manage").addEventListener("click", () => switchTab("bibliothek"));
  document.addEventListener("keydown", (event) => {
    if (
      event.key !== "/"
      || event.ctrlKey
      || event.metaKey
      || event.altKey
      || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")
      || document.activeElement?.isContentEditable
    ) return;
    const input = document.getElementById("global-search-input");
    if (!input) return;
    event.preventDefault();
    document.getElementById("global-search-shell").classList.add("is-expanded");
    input.focus();
  });
  document.getElementById("anime-search-btn").addEventListener("click", () => animeBrowse("search", 1));
  document.getElementById("anime-search").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    animeBrowse("search", 1);
  });
  document.getElementById("anime-search").addEventListener("blur", (event) => {
    if (!event.currentTarget.value.trim()) restoreAnimeSearchContext();
  });
  document.getElementById("anime-latest-btn").addEventListener("click", () => animeBrowse("latest", 1));
  document.getElementById("anime-trending-btn").addEventListener("click", () => animeBrowse("trending", 1));
  document.getElementById("anime-popular-btn").addEventListener("click", () => animeBrowse("popular", 1));
  document.getElementById("anime-prev").addEventListener("click", () => {
    animeBrowse(state.anime.mode || "latest", Math.max(1, state.anime.page - 1));
  });
  document.getElementById("anime-next").addEventListener("click", () => {
    animeBrowse(state.anime.mode || "latest", state.anime.page + 1);
  });
  document.getElementById("anime-select-page").addEventListener("click", () => {
    for (const episode of state.anime.current?.episodes || []) {
      if (!episode.queued && !episode.downloaded) state.anime.picked.add(episode.slug);
    }
    renderAnimeEpisodes();
  });
  document.getElementById("anime-select-none").addEventListener("click", () => {
    state.anime.picked.clear();
    renderAnimeEpisodes();
  });
  document.getElementById("anime-episode-prev").addEventListener("click", () => {
    if (!state.anime.current || state.anime.current.page <= 1) return;
    state.anime.episodePage = state.anime.current.page - 1;
    loadAnimeDetail({ keepSelection: true });
  });
  document.getElementById("anime-episode-next").addEventListener("click", () => {
    if (!state.anime.current || state.anime.current.page >= state.anime.current.page_count) return;
    state.anime.episodePage = state.anime.current.page + 1;
    loadAnimeDetail({ keepSelection: true });
  });
  document.getElementById("anime-add-btn").addEventListener("click", animeAddSelected);
  document.getElementById("watch-mode-close").addEventListener("click", closeWatchModeModal);
  document.getElementById("watch-mode-cancel").addEventListener("click", closeWatchModeModal);
  document.getElementById("watch-mode-save").addEventListener("click", saveWatchMode);
  document.getElementById("watch-mode-remove").addEventListener("click", removeWatchModeSubscription);
  document.querySelectorAll('input[name="watch-mode"]').forEach((radio) => {
    radio.addEventListener("change", updateWatchModeRequirement);
  });
  document.querySelectorAll('input[name="watch-cleanup"]').forEach((radio) => {
    radio.addEventListener("change", updateWatchModeRequirement);
  });
  document.getElementById("watch-mode-modal").addEventListener("click", (event) => {
    if (event.target.id === "watch-mode-modal") closeWatchModeModal();
  });

  // Bibliothek
  document.getElementById("wl-hero-open").addEventListener("click", () => {
    if (state.wl.heroBaseSlug) openWatchlistEntry(state.wl.heroBaseSlug);
  });
  document.getElementById("wl-hero-check").addEventListener("click", async () => {
    if (!state.wl.heroBaseSlug) return;
    document.getElementById("wl-status").textContent = "Archivstück wird geprüft …";
    const data = await api.watchlistCheck([state.wl.heroBaseSlug]);
    applyWatchlist(data.watchlist);
    document.getElementById("wl-status").textContent = "Status aktualisiert";
  });
  document.querySelectorAll("[data-library-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.wl.filter = button.dataset.libraryFilter || "all";
      renderWatchlist();
    });
  });
  document.getElementById("wl-search").addEventListener("input", (event) => {
    state.wl.draftQuery = event.currentTarget.value;
  });
  document.getElementById("wl-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    state.wl.query = String(state.wl.draftQuery || "").trim();
    renderWatchlist();
  });
  document.getElementById("wl-sort").addEventListener("change", (event) => {
    state.wl.sort = event.currentTarget.value || "attention";
    renderWatchlist();
  });
  document.getElementById("wl-check-all").addEventListener("click", async () => {
    document.getElementById("wl-status").textContent = `Prüfe ${state.wl.items.length} Serie(n) …`;
    const data = await api.watchlistCheck(null);
    applyWatchlist(data.watchlist);
    document.getElementById("wl-status").textContent = `${data.checked}/${data.total} geprüft`;
  });
  document.getElementById("wl-check-selected").addEventListener("click", async () => {
    if (!state.wl.selected.size) { alert("Bitte zuerst Serien in der Liste auswählen."); return; }
    const slugs = [...state.wl.selected];
    document.getElementById("wl-status").textContent = `Prüfe ${slugs.length} Serie(n) …`;
    const data = await api.watchlistCheck(slugs);
    applyWatchlist(data.watchlist);
    document.getElementById("wl-status").textContent = `${data.checked}/${data.total} geprüft`;
  });
  document.getElementById("wl-open").addEventListener("click", () => {
    const first = [...state.wl.selected][0];
    if (first) openWatchlistEntry(first);
  });
  document.getElementById("wl-remove").addEventListener("click", async () => {
    if (!state.wl.selected.size) return;
    const data = await api.watchlistRemove([...state.wl.selected]);
    state.wl.selected.clear();
    applyWatchlist(data.watchlist);
    await syncQueueSnapshot("Queue-Synchronisierung nach Abo-Entfernung");
  });

  // Benachrichtigungs-Glocke
  document.getElementById("notif-bell").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleNotifDropdown();
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".bell-wrap")) closeNotifDropdown();
  });
  document.getElementById("notif-refresh").addEventListener("click", refreshNotifications);
  document.getElementById("notif-library").addEventListener("click", () => {
    closeNotifDropdown();
    switchTab("bibliothek");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("movie-subscription-modal").classList.contains("hidden")) {
      event.preventDefault();
      closeMovieSubscriptionModal();
      return;
    }
    if (event.key === "Escape" && !document.getElementById("watch-mode-modal").classList.contains("hidden")) {
      event.preventDefault();
      closeWatchModeModal();
      return;
    }
    if (handleMediaModalKeydown(event)) return;
    if (event.key !== "Escape") return;
    closeNotifDropdown();
    setQueueDockExpanded(false);
    closeMobileQueue();
  });

  // Warteschlange / Downloads / Einstellungen
  document.getElementById("queue-clear").addEventListener("click", async () => {
    const resp = await api.queueClear();
    refreshQueueUiAfterChange(resp);
  });
  document.getElementById("serienstream-retry").addEventListener("click", async () => {
    const button = document.getElementById("serienstream-retry");
    button.disabled = true;
    try {
      const response = await api.serienstreamRetry();
      renderSerienstreamHealth(response.provider || {});
    } catch (error) {
      console.warn("SerienStream-Probe konnte nicht gestartet werden:", error);
    } finally {
      setTimeout(() => { button.disabled = false; }, 1500);
    }
  });
  document.getElementById("cancel-btn").addEventListener("click", async () => {
    const resp = await api.downloadCancel();
    refreshQueueUiAfterChange(resp);
    setDownloadState("cancelled", "Abgebrochen", "Downloads wurden gestoppt", state.download.percent);
  });
  document.getElementById("settings-btn").addEventListener("click", () => switchTab("einstellungen"));
  document.getElementById("settings-save").addEventListener("click", saveAllSettings);
  document.getElementById("taste-profile-reset").addEventListener("click", async () => {
    if (!window.confirm("Geschmacksprofil wirklich vollständig zurücksetzen?")) return;
    try {
      const response = await api.tasteReset();
      applyServerTasteProfile(response.profile);
      renderHome();
    } catch (error) {
      window.alert(`Profil konnte nicht zurückgesetzt werden: ${error.message}`);
    }
  });
  document.getElementById("ui-language").addEventListener("change", (event) => {
    i18n.changeLanguage(event.target.value, { userInitiated: true }).catch((error) => {
      console.warn("Sprache konnte nicht gewechselt werden:", error);
    });
  });
  document.getElementById("updater-check").addEventListener("click", () => checkForUpdates(true));
  document.getElementById("updater-install").addEventListener("click", installUpdate);
  document.getElementById("updater-channel").addEventListener("change", (event) => {
    const select = event.currentTarget;
    const previous = select.dataset.savedChannel || "stable";
    if (
      select.value === "overnight"
      && previous !== "overnight"
      && !window.confirm(
        "Zum Overnight-Kanal wechseln? Dieser Entwicklungskanal erhält Änderungen früher und kann instabil sein. Updates nutzen weiterhin Backup und Rollback.",
      )
    ) {
      select.value = previous;
    }
    document.getElementById("updater-channel-hint").textContent = select.value === "overnight"
      ? "Overnight · früher Zugriff aus overnight; kann instabil sein."
      : "Stable · geprüfte und freigegebene Änderungen aus main (empfohlen).";
  });
  document.getElementById("updater-mode").addEventListener("change", (event) => {
    document.getElementById("updater-interval").disabled = event.target.value !== "automatic";
    document.getElementById("updater-mode-status").textContent = event.target.value === "automatic"
      ? "Automatisch · wird nach dem Speichern aktiviert."
      : "Manuell · wird nach dem Speichern aktiviert.";
  });
  document.getElementById("seerr-sync").addEventListener("click", async () => {
    const button = document.getElementById("seerr-sync");
    const status = document.getElementById("seerr-status");
    button.disabled = true;
    status.textContent = "Prüfe Seerr-Anfragen …";
    try {
      applySeerrCfg(await api.seerrSync());
    } catch (error) {
      status.textContent = `✗ ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
  document.getElementById("jellyfin-users-load").addEventListener("click", () => loadJellyfinUsers({
    urlId: "jellyfin-url", keyId: "jellyfin-api-key", selectId: "jellyfin-user-id",
    buttonId: "jellyfin-users-load", statusId: "jellyfin-user-status",
  }));
  document.getElementById("browse-dir-btn").addEventListener("click", () => {
    dirModalTarget = "save-path";
    openDirModal(document.getElementById("save-path").value);
  });
  document.getElementById("browse-series-btn").addEventListener("click", () => {
    dirModalTarget = "series-path";
    openDirModal(document.getElementById("series-path").value);
  });
  document.getElementById("dir-modal-close").addEventListener("click", () => {
    document.getElementById("dir-modal").classList.add("hidden");
  });
  document.getElementById("dir-modal-select").addEventListener("click", () => {
    // Nur ins gewählte Feld übernehmen – persistiert wird über "Speichern".
    document.getElementById(dirModalTarget).value = dirModalPath;
    document.getElementById("dir-modal").classList.add("hidden");
  });

  // Ersteinrichtung
  document.getElementById("setup-browse-movies").addEventListener("click", () => {
    dirModalTarget = "setup-save-path";
    openDirModal(document.getElementById("setup-save-path").value);
  });
  document.getElementById("setup-browse-series").addEventListener("click", () => {
    dirModalTarget = "setup-series-path";
    openDirModal(document.getElementById("setup-series-path").value);
  });
  document.getElementById("setup-jellyfin-users-load").addEventListener("click", () => loadJellyfinUsers({
    urlId: "setup-jellyfin-url", keyId: "setup-jellyfin-key", selectId: "setup-jellyfin-user",
    buttonId: "setup-jellyfin-users-load",
  }));
  document.getElementById("setup-ui-language").addEventListener("change", (event) => {
    i18n.changeLanguage(event.target.value, { userInitiated: true }).catch((error) => {
      setSetupStatus(`Sprache konnte nicht geladen werden: ${error.message}`, true);
    });
  });
  document.getElementById("setup-next").addEventListener("click", () => {
    if (validateSetupStep(setupStep)) showSetupStep(setupStep + 1);
  });
  document.getElementById("setup-back").addEventListener("click", () => showSetupStep(setupStep - 1));
  document.getElementById("setup-finish").addEventListener("click", finishSetup);
  document.getElementById("setup-wizard").addEventListener("keydown", (e) => {
    if (!setupRequired || e.key !== "Enter" || e.target.closest("button") || e.target.type === "checkbox") return;
    e.preventDefault();
    if (setupStep < SETUP_STEP_COUNT) {
      if (validateSetupStep(setupStep)) showSetupStep(setupStep + 1);
    } else {
      finishSetup();
    }
  });

  document.getElementById("account-save").addEventListener("click", saveAccount);
  document.getElementById("account-logout").addEventListener("click", logoutAccount);
  document.getElementById("account-revoke").addEventListener("click", revokeOtherSessions);

  try {
    await initSettings();
  } catch (e) {
    console.error("Einstellungen konnten nicht geladen werden:", e);
  }
  const needsSetup = await initSetupWizard();
  if (!needsSetup) startInitialData();
}

document.addEventListener("DOMContentLoaded", initApp);
