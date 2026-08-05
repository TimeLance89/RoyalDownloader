// ── Filme-Tab ──────────────────────────────────────────────────────────────
const MOVIE_FEATURE_INTERVAL_MS = 9000;
const MOVIE_FEATURE_MAX_AGE_DAYS = 270;
const MOVIE_FEATURE_MAX_FUTURE_DAYS = 45;

function movieFeatureCandidate(result) {
  const metadata = state.fp.metadataCache[result.slug] || {};
  const backdrop = metadata.backdrop_url || result.backdrop_url || "";
  const cover = metadata.cover_url || result.cover_url || "";
  const artwork = backdrop || cover;

  const now = new Date();
  const release = metadata.release_date ? new Date(`${metadata.release_date}T12:00:00`) : null;
  let ageDays = null;
  if (release && !Number.isNaN(release.getTime())) {
    ageDays = (now.getTime() - release.getTime()) / 86400000;
    if (ageDays > MOVIE_FEATURE_MAX_AGE_DAYS || ageDays < -MOVIE_FEATURE_MAX_FUTURE_DAYS) {
      return null;
    }
  } else {
    const year = Number(metadata.year || result.year) || 0;
    if (year && year < now.getFullYear() - 1) return null;
  }

  const year = Number(metadata.year || result.year) || 0;
  const rating = Number(metadata.rating) || 0;
  const votes = Number(metadata.vote_count) || 0;
  const recencyScore = ageDays == null
    ? (year === now.getFullYear() ? 36 : (year === now.getFullYear() - 1 ? 20 : 26))
    : (ageDays >= 0 ? 70 - Math.min(ageDays, 365) * 0.1 : 54 - Math.abs(ageDays) * 0.2);
  const score = recencyScore
    + rating * 2
    + Math.min(14, Math.log10(votes + 1) * 3)
    + (backdrop ? 24 : 8)
    + (metadata.description ? 7 : 0);
  return {
    ...result,
    ...metadata,
    artwork,
    artworkKind: backdrop ? "backdrop" : (cover ? "poster" : "none"),
    featureScore: score,
  };
}

function stopMovieFeatureRotation() {
  if (!state.fp.featureTimer) return;
  clearInterval(state.fp.featureTimer);
  state.fp.featureTimer = null;
}

function scheduleMovieFeatureRotation() {
  stopMovieFeatureRotation();
  const feature = document.getElementById("movie-feature");
  if (
    !feature
    || feature.classList.contains("hidden")
    || state.tab !== "filme"
    || state.fp.featurePaused
    || state.fp.featureCandidates.length < 2
    || feature.matches(":hover")
    || feature.contains(document.activeElement)
    || document.hidden
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) return;
  state.fp.featureTimer = window.setInterval(() => {
    showMovieFeature(state.fp.featureIndex + 1);
  }, MOVIE_FEATURE_INTERVAL_MS);
}

function setMovieFeaturePaused(paused) {
  state.fp.featurePaused = paused;
  const button = document.getElementById("movie-feature-pause");
  if (button) {
    button.textContent = paused ? "▶" : "Ⅱ";
    button.setAttribute("aria-label", paused ? "Rotation fortsetzen" : "Rotation pausieren");
    button.setAttribute("aria-pressed", String(paused));
  }
  if (paused) stopMovieFeatureRotation();
  else scheduleMovieFeatureRotation();
}

function movieFeatureDate(candidate) {
  if (!candidate.release_date) return candidate.year || "";
  const date = new Date(`${candidate.release_date}T12:00:00`);
  if (Number.isNaN(date.getTime())) return candidate.year || "";
  return date.toLocaleDateString(i18n.locale(), {
    day: "2-digit", month: "short", year: "numeric",
  });
}

function renderMovieFeature() {
  const feature = document.getElementById("movie-feature");
  const candidates = state.fp.featureCandidates;
  const candidate = candidates[state.fp.featureIndex];
  if (!feature || !candidate) {
    feature?.classList.add("hidden");
    stopMovieFeatureRotation();
    return;
  }

  feature.classList.remove("hidden");
  feature.classList.toggle("is-poster-art", candidate.artworkKind === "poster");
  feature.classList.toggle("has-no-art", candidate.artworkKind === "none");
  feature.setAttribute("aria-label", `Aktuelle Kinofilme: ${candidate.title}`);
  document.getElementById("movie-feature-art").style.backgroundImage = candidate.artwork
    ? `url("${api.coverUrl(candidate.artwork).replace(/"/g, "%22")}")`
    : "";
  document.getElementById("movie-feature-title").textContent = candidate.title;
  document.getElementById("movie-feature-count").textContent =
    `${state.fp.featureIndex + 1} / ${candidates.length}`;
  document.getElementById("movie-feature-description").textContent =
    candidate.description || "Neu bei deinen ausgewählten Filmquellen.";
  const provider = state.providers.labels[candidate.provider] || "";
  document.getElementById("movie-feature-meta").textContent = [
    movieFeatureDate(candidate),
    candidate.rating ? `★ ${candidate.rating}` : "",
    ...(candidate.genres || []).slice(0, 2),
    provider,
  ].filter(Boolean).join(" · ");
  document.getElementById("movie-feature-open").dataset.slug = candidate.slug;

  const dots = document.getElementById("movie-feature-dots");
  dots.innerHTML = "";
  candidates.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = index === state.fp.featureIndex ? "is-active" : "";
    button.setAttribute("aria-label", `${item.title} anzeigen`);
    button.setAttribute("aria-pressed", String(index === state.fp.featureIndex));
    button.addEventListener("click", () => {
      showMovieFeature(index, true);
      scheduleMovieFeatureRotation();
    });
    dots.appendChild(button);
  });
}

function showMovieFeature(index, userInitiated = false) {
  const count = state.fp.featureCandidates.length;
  if (!count) return;
  state.fp.featureIndex = ((index % count) + count) % count;
  const feature = document.getElementById("movie-feature");
  if (!userInitiated && feature) {
    feature.classList.add("is-changing");
    window.setTimeout(() => feature.classList.remove("is-changing"), 360);
  }
  renderMovieFeature();
}

function refreshMovieFeatureCandidates() {
  if (state.fp.category !== "new") {
    document.getElementById("movie-feature")?.classList.add("hidden");
    stopMovieFeatureRotation();
    return;
  }
  const currentSlug = state.fp.featureCandidates[state.fp.featureIndex]?.slug;
  const seenTitles = new Set();
  const allCandidates = state.fp.results
    .map(movieFeatureCandidate)
    .filter(Boolean)
    .sort((a, b) => b.featureScore - a.featureScore)
    .filter((candidate) => {
      const key = String(candidate.title || "").trim().toLocaleLowerCase();
      if (!key || seenTitles.has(key)) return false;
      seenTitles.add(key);
      return true;
    });
  const artworkCandidates = allCandidates.filter((candidate) => candidate.artwork);
  const candidates = (artworkCandidates.length ? artworkCandidates : allCandidates).slice(0, 5);
  state.fp.featureCandidates = candidates;
  const preservedIndex = candidates.findIndex((candidate) => candidate.slug === currentSlug);
  state.fp.featureIndex = preservedIndex >= 0 ? preservedIndex : 0;
  renderMovieFeature();
  scheduleMovieFeatureRotation();
  renderHomeHero();
}

function homeMovieBySlug(slug) {
  return [
    ...state.home.newMovies,
    ...state.home.topMovies,
    ...state.home.discoveryMovies,
    ...state.home.search.results.filter((entry) => entry.kind === "movie").map((entry) => entry.item),
    ...state.globalSearch.results.filter((entry) => entry.kind === "movie").map((entry) => entry.item),
  ]
    .find((item) => item.slug === slug) || null;
}

function homeSeriesBySlug(baseSlug) {
  return [
    ...state.home.trendingSeries,
    ...state.home.newSeries,
    ...state.home.discoverySeries,
    ...state.home.search.results.filter((entry) => entry.kind === "series").map((entry) => entry.item),
    ...state.globalSearch.results.filter((entry) => entry.kind === "series").map((entry) => entry.item),
  ]
    .find((item) => item.base_slug === baseSlug) || null;
}

function homeAnimeById(id) {
  return [
    ...state.anime.results,
    ...state.globalSearch.results.filter((entry) => entry.kind === "anime").map((entry) => entry.item),
  ].find((item) => String(item.id) === String(id)) || null;
}

function mediaJellyfinStatus(media) {
  if (media?.jellyfin_status) return media.jellyfin_status;
  if (typeof media?.in_jellyfin === "boolean") return media.in_jellyfin ? "owned" : "missing";
  return "checking";
}

function jellyfinStatusText(status) {
  const labels = {
    owned: "✓ In Jellyfin",
    missing: "Fehlt in Jellyfin",
    checking: "Jellyfin wird geprüft",
    unavailable: "Jellyfin nicht erreichbar",
    unconfigured: "Jellyfin nicht verbunden",
    ambiguous: "Jellyfin-Zuordnung unklar",
  };
  return labels[status] || labels.checking;
}

function setCatalogJellyfinBadge(badge, status) {
  const labels = {
    owned: "✓ In Jellyfin",
    missing: "Fehlt in Jellyfin",
    checking: "Jellyfin wird geprüft",
    unavailable: "Jellyfin nicht erreichbar",
    unconfigured: "Jellyfin nicht verbunden",
    ambiguous: "Jellyfin-Zuordnung unklar",
  };
  const normalized = labels[status] ? status : "checking";
  badge.className = `catalog-jellyfin-badge is-${normalized}`;
  badge.textContent = normalized === "owned" ? "✓ JF" : normalized === "missing" ? "– JF" : "JF ?";
  badge.title = labels[normalized];
  badge.setAttribute("aria-label", labels[normalized]);
}

async function refreshCatalogJellyfinStatus(entries, render) {
  const unique = uniqueHomeEntries(entries);
  if (!unique.length) return;
  const requests = unique.map(({ kind, item }) => ({
    slug: homeEntryKey({ kind, item }),
    title: item.title,
    year: item.year || "",
    tmdb_id: item.tmdb_id || (kind === "movie" ? state.fp.metadataCache[item.slug]?.tmdb_id : null) || null,
    media_type: kind === "movie" ? "movie" : "series",
  }));
  try {
    const response = await api.jellyfinMatches(requests);
    for (const entry of unique) {
      const key = homeEntryKey(entry);
      const status = response.statuses?.[key]
        || (Object.hasOwn(response.matches || {}, key)
          ? (response.matches[key] ? "owned" : "missing")
          : (response.configured ? "unavailable" : "unconfigured"));
      entry.item.jellyfin_status = status;
      if (status === "owned" || status === "missing") entry.item.in_jellyfin = status === "owned";
    }
  } catch {
    unique.forEach((entry) => { entry.item.jellyfin_status = "unavailable"; });
  }
  if (render) render();
}

function refreshAllCatalogJellyfinStatuses() {
  const entries = [
    ...homeAllEntries(),
    ...state.series.results.map(homeSeriesEntry),
    ...state.anime.results.map(homeAnimeEntry),
    ...state.globalSearch.results,
  ];
  return refreshCatalogJellyfinStatus(entries, () => {
    renderHome();
    renderSeriesResults();
    renderAnimeResults();
    renderGlobalSearchResults();
  });
}

function uniqueHomeEntries(entries) {
  const seen = new Set();
  return entries.filter((entry) => {
    if (!entry?.item) return false;
    const key = homeEntryKey(entry);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function interleaveHomeEntries(primary, secondary, limit = 20) {
  const mixed = [];
  const max = Math.max(primary.length, secondary.length);
  for (let index = 0; index < max && mixed.length < limit; index += 1) {
    if (primary[index]) mixed.push(primary[index]);
    if (secondary[index] && mixed.length < limit) mixed.push(secondary[index]);
  }
  return uniqueHomeEntries(mixed).slice(0, limit);
}

function homeMovieEntry(item) {
  return { kind: "movie", item };
}

function homeSeriesEntry(item) {
  return { kind: "series", item };
}

function homeAnimeEntry(item) {
  return { kind: "anime", item };
}

const HOME_DISCOVERY_PROFILE_KEY = "royal-discovery-profile-v1";
const HOME_WEEKLY_TOP_KEY = "royal-home-weekly-top-v1";

function homeEntryKey(entry) {
  if (!entry?.item) return "";
  const key = entry.kind === "movie"
    ? entry.item.slug
    : entry.kind === "anime" ? entry.item.id : entry.item.base_slug;
  return `${entry.kind}:${key}`;
}

function homeEntryMedia(entry) {
  if (!entry?.item) return {};
  const metadata = entry.kind === "movie"
    ? (state.fp.metadataCache[entry.item.slug] || {})
    : {};
  return { ...entry.item, ...metadata };
}

function localDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localWeekKey(date = new Date()) {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const weekday = monday.getDay() || 7;
  monday.setDate(monday.getDate() - weekday + 1);
  return localDateKey(monday);
}

function stableDiscoveryHash(value) {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function stableDailyOrder(entries, lane) {
  const seed = `${localDateKey()}|${lane}`;
  return entries.slice().sort((a, b) =>
    stableDiscoveryHash(`${seed}|${homeEntryKey(a)}`)
    - stableDiscoveryHash(`${seed}|${homeEntryKey(b)}`));
}

function loadDiscoveryProfile() {
  let profile = null;
  try {
    profile = JSON.parse(localStorage.getItem(HOME_DISCOVERY_PROFILE_KEY) || "null");
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
    localStorage.setItem(HOME_DISCOVERY_PROFILE_KEY, JSON.stringify(profile));
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
  const localProfile = loadDiscoveryProfile();
  try {
    let serverProfile = await api.tasteProfile();
    if (!serverProfile.legacy_imported && localProfile.interactions > 0) {
      const imported = await api.tasteImport({
        genres: localProfile.genres || {},
        kinds: localProfile.kinds || {},
      });
      serverProfile = imported.profile || serverProfile;
    }
    applyServerTasteProfile(serverProfile);
    if (state.tab === "home") renderHome();
  } catch (error) {
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

function renderTasteProfileSummary(profile = loadDiscoveryProfile(), offline = false) {
  const target = document.getElementById("taste-profile-summary");
  if (!target) return;
  const favorites = Object.entries(profile.genres || {})
    .filter(([, score]) => Number(score) > .25)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 5)
    .map(([name]) => name);
  const learned = Number(profile.interactions || 0);
  target.textContent = learned
    ? `${learned} Signale${favorites.length ? ` · Besonders: ${favorites.join(", ")}` : ""}${offline ? " · nur lokaler Stand" : ""}`
    : "Noch neutral – Royal lernt erst durch deine Bedienung.";
}

function currentTasteTarget(kind) {
  if (kind === "movie") {
    const slug = state.fp.selectedSlug || "";
    const item = {
      ...(homeMovieBySlug(slug) || {}),
      ...(state.fp.moviesCache[slug] || {}),
      ...(state.fp.metadataCache[slug] || {}),
      slug,
    };
    return slug ? { key: `movie:${slug}`, item } : null;
  }
  const item = state.series.current;
  return item?.base_slug ? { key: `series:${item.base_slug}`, item } : null;
}

function updateTasteFeedbackButtons() {
  const profile = loadDiscoveryProfile();
  for (const [kind, prefix] of [["movie", "fp"], ["series", "series"]]) {
    const target = currentTasteTarget(kind);
    const action = target ? profile.item_feedback?.[target.key] : "";
    const like = document.getElementById(`${prefix}-taste-like`);
    const dislike = document.getElementById(`${prefix}-taste-dislike`);
    if (!like || !dislike) continue;
    like.disabled = !target;
    dislike.disabled = !target;
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
  const target = currentTasteTarget(kind);
  if (!target) return;
  const currentAction = loadDiscoveryProfile().item_feedback?.[target.key] || "";
  const sameChoice = requestedAction === "like"
    ? ["like", "favorite"].includes(currentAction)
    : ["dislike", "dismiss"].includes(currentAction);
  const action = sameChoice ? "clear" : requestedAction;
  try {
    const response = await api.tasteFeedback({
      item_key: target.key,
      action,
      source: "web",
      media_type: kind,
      title: target.item.title || "",
      metadata: tasteMetadata(kind, target.item),
    });
    applyServerTasteProfile(response.profile);
    renderHome();
  } catch (error) {
    console.warn("Bewertung konnte nicht gespeichert werden:", error);
  }
}

function trackDiscoveryPreference(kind, item, weight = 1, action = "open") {
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
  api.tasteEvent({
    action,
    source: "web",
    media_type: kind,
    item_key: key,
    title: item.title || "",
    metadata: tasteMetadata(kind, media),
  }).then((response) => {
    if (response?.profile) applyServerTasteProfile(response.profile);
  }).catch((error) => console.warn("Geschmackssignal konnte nicht gespeichert werden:", error));
}

function allowedHomeEntries(entries, profile = loadDiscoveryProfile()) {
  const blocked = new Set(profile.blocked_items || []);
  return entries.filter((entry) => !blocked.has(homeEntryKey(entry)));
}

function homeAllEntries() {
  return allowedHomeEntries(uniqueHomeEntries([
    ...state.home.topMovies.map(homeMovieEntry),
    ...state.home.newMovies.map(homeMovieEntry),
    ...state.home.discoveryMovies.map(homeMovieEntry),
    ...state.home.trendingSeries.map(homeSeriesEntry),
    ...state.home.newSeries.map(homeSeriesEntry),
    ...state.home.discoverySeries.map(homeSeriesEntry),
  ]));
}

function weeklyStableEntries(entries, limit = 10) {
  const period = localWeekKey();
  const available = new Map(entries.map((entry) => [homeEntryKey(entry), entry]));
  let stored = null;
  try {
    stored = JSON.parse(localStorage.getItem(HOME_WEEKLY_TOP_KEY) || "null");
  } catch {
    stored = null;
  }
  const previousKeys = stored?.period === period && Array.isArray(stored.keys) ? stored.keys : [];
  const ordered = previousKeys.map((key) => available.get(key)).filter(Boolean);
  const known = new Set(ordered.map(homeEntryKey));
  const fill = entries
    .filter((entry) => !known.has(homeEntryKey(entry)))
    .sort((a, b) =>
      stableDiscoveryHash(`${period}|top|${homeEntryKey(a)}`)
      - stableDiscoveryHash(`${period}|top|${homeEntryKey(b)}`));
  const selected = [...ordered, ...fill].slice(0, limit);
  try {
    localStorage.setItem(HOME_WEEKLY_TOP_KEY, JSON.stringify({
      period,
      keys: selected.map(homeEntryKey),
    }));
  } catch {
    // Die Reihenfolge bleibt für diese Sitzung trotzdem stabil.
  }
  return selected;
}

function homeTopEntries() {
  return weeklyStableEntries(allowedHomeEntries(interleaveHomeEntries(
    state.home.topMovies.map(homeMovieEntry),
    state.home.trendingSeries.map(homeSeriesEntry),
    20,
  )), 10);
}

function homeNewEntries() {
  return allowedHomeEntries(interleaveHomeEntries(
    state.home.newMovies.map(homeMovieEntry),
    state.home.newSeries.map(homeSeriesEntry),
    24,
  ));
}

function homePopularSeriesEntries() {
  const preferred = state.home.trendingSeries.length
    ? state.home.trendingSeries
    : uniqueHomeEntries([
      ...state.home.newSeries.map(homeSeriesEntry),
      ...state.home.discoverySeries.map(homeSeriesEntry),
    ]).map((entry) => entry.item);
  const title = document.getElementById("home-series-title");
  if (title) {
    title.textContent = state.home.trendingSeries.length
      ? "Serien, die gerade alle sehen"
      : "Serien aus deinen aktiven Quellen";
  }
  return allowedHomeEntries(preferred.map(homeSeriesEntry));
}

function homePersonalizedEntries() {
  const profile = loadDiscoveryProfile();
  const recent = new Set(profile.recent.slice(0, 18).map((event) => event.key));
  const pool = homeAllEntries();
  if (profile.interactions < 2 || !Object.keys(profile.genres).length) {
    return stableDailyOrder(pool.filter((entry) => !recent.has(homeEntryKey(entry))), "starter").slice(0, 24);
  }
  return pool
    .filter((entry) => !recent.has(homeEntryKey(entry)))
    .map((entry) => {
      const media = homeEntryMedia(entry);
      const metadata = tasteMetadata(entry.kind, media);
      const dimensionScore = Object.entries(metadata).reduce((total, [dimension, values]) => {
        if (!["genres", "tags", "studios", "directors", "actors", "languages"].includes(dimension)) return total;
        const list = Array.isArray(values) ? values : [values];
        return total + list.reduce(
          (sum, value) => sum + Number(profile.dimensions?.[dimension]?.[String(value)] || 0), 0,
        );
      }, 0);
      const year = Number(String(metadata.year || "").slice(0, 4));
      const decadeScore = year
        ? Number(profile.dimensions?.decades?.[`${Math.floor(year / 10) * 10}er`] || 0)
        : 0;
      const kindScore = Number(profile.kinds[entry.kind] || 0);
      const rating = Number(media.rating || 0);
      const discoveryNoise = stableDiscoveryHash(`${localDateKey()}|personal|${homeEntryKey(entry)}`) / 4294967295;
      return { entry, score: dimensionScore + decadeScore + kindScore + rating * 0.12 + discoveryNoise * 2.2 };
    })
    .sort((a, b) => b.score - a.score)
    .map(({ entry }) => entry)
    .slice(0, 24);
}

function favoriteDiscoveryGenre(profile = loadDiscoveryProfile()) {
  return Object.entries(profile.genres)
    .filter(([, score]) => Number(score) > 0.25)
    .sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0], "de"))[0]?.[0] || "";
}

function homeGenreEntries() {
  const profile = loadDiscoveryProfile();
  const favorite = favoriteDiscoveryGenre(profile);
  const pool = homeAllEntries();
  if (!favorite) return stableDailyOrder(pool, "genre-starter").slice(0, 24);
  const matching = pool.filter((entry) =>
    (homeEntryMedia(entry).genres || []).some((genre) =>
      String(genre).localeCompare(favorite, "de", { sensitivity: "base" }) === 0));
  return stableDailyOrder(matching.length >= 6 ? matching : pool, `genre-${favorite}`).slice(0, 24);
}

function homeExploreEntries() {
  const profile = loadDiscoveryProfile();
  const avoidedGenres = new Set(Object.entries(profile.genres)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 2)
    .map(([genre]) => genre.toLocaleLowerCase()));
  const recent = new Set(profile.recent.slice(0, 30).map((event) => event.key));
  const pool = homeAllEntries().filter((entry) => {
    if (recent.has(homeEntryKey(entry))) return false;
    const genres = (homeEntryMedia(entry).genres || []).map((genre) => String(genre).toLocaleLowerCase());
    return !genres.some((genre) => avoidedGenres.has(genre));
  });
  return stableDailyOrder(pool.length >= 8 ? pool : homeAllEntries(), "explore").slice(0, 24);
}

function homeGemEntries() {
  const topKeys = new Set(homeTopEntries().map(homeEntryKey));
  const candidates = homeAllEntries()
    .filter((entry) => !topKeys.has(homeEntryKey(entry)))
    .map((entry) => ({ entry, rating: Number(homeEntryMedia(entry).rating || 0) }))
    .filter(({ rating }) => !rating || rating >= 6.4)
    .sort((a, b) => b.rating - a.rating
      || stableDiscoveryHash(`${localDateKey()}|gems|${homeEntryKey(a.entry)}`)
      - stableDiscoveryHash(`${localDateKey()}|gems|${homeEntryKey(b.entry)}`))
    .map(({ entry }) => entry);
  return candidates.slice(0, 24);
}

function homeHeroCandidates() {
  const entries = uniqueHomeEntries([
    ...homePersonalizedEntries().slice(0, 4),
    ...stableDailyOrder(homeTopEntries(), "hero").slice(0, 3),
  ]).slice(0, 7);
  return entries.map((entry) => {
    const metadata = entry.kind === "movie"
      ? (state.fp.metadataCache[entry.item.slug] || {})
      : {};
    const media = { ...entry.item, ...metadata };
    return {
      ...entry,
      media,
      artwork: media.backdrop_url || media.cover_url || "",
      artworkKind: media.backdrop_url ? "backdrop" : (media.cover_url ? "poster" : "none"),
    };
  });
}

function stopHomeHeroRotation() {
  if (!state.home.heroTimer) return;
  window.clearInterval(state.home.heroTimer);
  state.home.heroTimer = null;
}

function scheduleHomeHeroRotation() {
  stopHomeHeroRotation();
  const hero = document.getElementById("home-hero");
  if (
    !hero
    || state.tab !== "home"
    || homeHeroCandidates().length < 2
    || hero.matches(":hover")
    || hero.contains(document.activeElement)
    || document.hidden
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) return;
  state.home.heroTimer = window.setInterval(() => {
    showHomeHero(state.home.heroIndex + 1);
  }, 9000);
}

function renderHomeHero() {
  const hero = document.getElementById("home-hero");
  if (!hero) return;
  const candidates = homeHeroCandidates();
  if (!candidates.length) {
    hero.classList.add("is-loading", "has-no-art");
    document.getElementById("home-hero-open").disabled = true;
    return;
  }
  state.home.heroIndex = ((state.home.heroIndex % candidates.length) + candidates.length) % candidates.length;
  const candidate = candidates[state.home.heroIndex];
  const media = candidate.media;
  hero.classList.remove("is-loading");
  hero.classList.toggle("is-poster-art", candidate.artworkKind === "poster");
  hero.classList.toggle("has-no-art", candidate.artworkKind === "none");
  hero.setAttribute("aria-label", `${candidate.kind === "movie" ? "Film" : "Serie"}: ${media.title}`);
  document.getElementById("home-hero-art").style.backgroundImage = candidate.artwork
    ? `url("${api.coverUrl(candidate.artwork).replace(/"/g, "%22")}")`
    : "";
  document.getElementById("home-hero-kind").textContent =
    candidate.kind === "movie" ? "ROYAL FILM" : "ROYAL SERIE";
  document.getElementById("home-hero-title").textContent = media.title || "Royal";
  document.getElementById("home-hero-meta").textContent = [
    media.year || (media.first_air_date ? String(media.first_air_date).slice(0, 4) : ""),
    media.rating ? `★ ${media.rating}` : "",
    ...(media.genres || []).slice(0, 2),
    candidate.kind === "movie" ? "Film" : "Serie",
  ].filter(Boolean).join(" · ");
  document.getElementById("home-hero-description").textContent =
    media.description
    || (candidate.kind === "movie"
      ? "Neu und beliebt bei deinen ausgewählten Filmquellen."
      : "Eine aktuell angesagte Serie aus deinen eingerichteten Quellen.");
  const open = document.getElementById("home-hero-open");
  open.disabled = false;
  open.dataset.kind = candidate.kind;
  open.dataset.key = candidate.kind === "movie" ? media.slug : media.base_slug;
  document.getElementById("home-hero-position").textContent =
    `${state.home.heroIndex + 1} / ${candidates.length}`;
}

function showHomeHero(index, userInitiated = false) {
  const count = homeHeroCandidates().length;
  if (!count) return;
  state.home.heroIndex = ((index % count) + count) % count;
  const hero = document.getElementById("home-hero");
  if (!userInitiated && hero) {
    hero.classList.add("is-changing");
    window.setTimeout(() => hero.classList.remove("is-changing"), 380);
  }
  renderHomeHero();
}

function openHomeEntry(kind, key) {
  if (kind === "movie") {
    const movie = homeMovieBySlug(key);
    closeGlobalSearch();
    if (movie) selectFpRow(movie.slug, movie);
    return;
  }
  if (kind === "anime") {
    const anime = homeAnimeById(key);
    closeGlobalSearch();
    if (anime) openAnimeDetail(anime);
    return;
  }
  const series = homeSeriesBySlug(key);
  closeGlobalSearch();
  if (series) loadSeries(series);
}

function updateHomeCardHoverEdge(card) {
  if (!card || card.classList.contains("is-ranked")) return;
  const track = card.closest(".home-track");
  if (!track) return;
  const cardRect = card.getBoundingClientRect();
  const trackRect = track.getBoundingClientRect();
  const growth = cardRect.width * 0.35;
  const clipsLeft = cardRect.left - growth < trackRect.left;
  const clipsRight = cardRect.right + growth > trackRect.right;
  card.classList.toggle("is-hover-edge-left", clipsLeft && !clipsRight);
  card.classList.toggle("is-hover-edge-right", clipsRight && !clipsLeft);
  if (clipsLeft && clipsRight) {
    const useLeft = cardRect.left + (cardRect.width / 2) < trackRect.left + (trackRect.width / 2);
    card.classList.toggle("is-hover-edge-left", useLeft);
    card.classList.toggle("is-hover-edge-right", !useLeft);
  }
}

function updateHomeRailNavigation(track) {
  if (!track?.id) return;
  const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
  const canScroll = maxScroll > 2;
  const atStart = track.scrollLeft <= 2;
  const atEnd = track.scrollLeft >= maxScroll - 2;
  document.querySelectorAll(`[data-home-scroll="${track.id}"]`).forEach((button) => {
    const direction = Number(button.dataset.direction) || 1;
    button.hidden = !canScroll || (direction < 0 ? atStart : atEnd);
  });
}

function createHomeCard(entry, rank = 0, eager = false) {
  const { kind, item } = entry;
  const metadata = kind === "movie" ? (state.fp.metadataCache[item.slug] || {}) : {};
  const media = { ...item, ...metadata };
  const key = kind === "movie" ? item.slug : kind === "anime" ? item.id : item.base_slug;
  const card = document.createElement("button");
  card.type = "button";
  card.className = `home-card home-card-${kind}${rank ? " is-ranked" : ""}`;
  card.dataset.kind = kind;
  card.dataset.key = key;
  const kindLabel = kind === "movie" ? "Film" : kind === "anime" ? "Anime" : "Serie";
  card.setAttribute("aria-label", `${rank ? `Platz ${rank}: ` : ""}${media.title}, ${kindLabel}, ${jellyfinStatusText(mediaJellyfinStatus(media))}`);

  if (rank) {
    const number = document.createElement("span");
    number.className = "home-card-rank";
    number.textContent = String(rank);
    number.setAttribute("aria-hidden", "true");
    card.appendChild(number);
  }

  const art = document.createElement("span");
  art.className = "home-card-art";
  const fallback = document.createElement("span");
  fallback.className = "home-card-fallback";
  fallback.textContent = mediaCardInitials(media.title);
  art.appendChild(fallback);
  // Das bevorzugte Format bleibt erhalten, vorhandenes alternatives Artwork
  // verhindert aber leere Karten bei Titeln ohne TMDB-Backdrop oder -Poster.
  const artworkCandidates = [
    rank ? media.cover_url : media.backdrop_url,
    rank ? media.backdrop_url : media.cover_url,
  ]
    .flatMap((url) => api.coverCandidates(url))
    .filter((url, index, urls) => url && urls.indexOf(url) === index);
  if (artworkCandidates.length) {
    const image = document.createElement("img");
    let artworkIndex = 0;
    image.src = artworkCandidates[artworkIndex];
    image.alt = "";
    // Die Startseite zeigt nur kuratierte Rails. Ihre Bilder werden sofort
    // geladen, damit beim horizontalen Scrollen keine Platzhalter aufblitzen.
    image.loading = "eager";
    image.fetchPriority = eager ? "high" : "auto";
    image.decoding = "async";
    image.addEventListener("error", () => {
      artworkIndex += 1;
      if (artworkIndex < artworkCandidates.length) image.src = artworkCandidates[artworkIndex];
      else image.remove();
    });
    art.appendChild(image);
  }
  const type = document.createElement("span");
  type.className = "home-card-type";
  type.textContent = kindLabel.toLocaleUpperCase("de-DE");
  const jellyfin = document.createElement("span");
  setCatalogJellyfinBadge(jellyfin, mediaJellyfinStatus(media));
  const overlay = document.createElement("span");
  overlay.className = "home-card-overlay";
  const title = document.createElement("strong");
  title.translate = false;
  title.textContent = media.title;
  const meta = document.createElement("span");
  meta.textContent = [
    media.year || "",
    media.rating ? `★ ${media.rating}` : "",
  ].filter(Boolean).join(" · ") || (kind === "movie" ? "Film" : "Serie");
  overlay.append(title, meta);

  const preview = document.createElement("span");
  preview.className = "home-card-preview";
  preview.setAttribute("aria-hidden", "true");
  const previewActions = document.createElement("span");
  previewActions.className = "home-card-preview-actions";
  const playMark = document.createElement("span");
  playMark.className = "is-play";
  playMark.textContent = "▶";
  const addMark = document.createElement("span");
  addMark.className = "is-add";
  addMark.textContent = "+";
  const moreMark = document.createElement("span");
  moreMark.className = "is-more";
  moreMark.textContent = "⌄";
  previewActions.append(playMark, addMark, moreMark);
  const previewTitle = document.createElement("strong");
  previewTitle.translate = false;
  previewTitle.textContent = media.title;
  const previewMeta = document.createElement("span");
  previewMeta.className = "home-card-preview-meta";
  previewMeta.textContent = [
    media.rating ? `★ ${media.rating}` : "",
    media.year || "",
    media.runtime || "",
    kindLabel,
  ].filter(Boolean).join(" · ");
  const previewGenres = document.createElement("span");
  previewGenres.className = "home-card-preview-genres";
  previewGenres.textContent = (media.genres || []).slice(0, 3).join(" · ")
    || `${kindLabel} entdecken`;
  preview.append(previewActions, previewTitle, previewMeta, previewGenres);

  art.append(type, jellyfin, overlay, preview);
  card.appendChild(art);
  card.addEventListener("pointerenter", () => updateHomeCardHoverEdge(card));
  card.addEventListener("pointerleave", () => {
    card.classList.remove("is-hover-edge-left", "is-hover-edge-right");
  });
  card.addEventListener("focus", () => updateHomeCardHoverEdge(card));
  card.addEventListener("blur", () => {
    card.classList.remove("is-hover-edge-left", "is-hover-edge-right");
  });
  card.addEventListener("click", () => openHomeEntry(kind, key));
  return card;
}

function renderHomeRail(trackId, entries, { ranked = false } = {}) {
  const track = document.getElementById(trackId);
  if (!track) return;
  track.replaceChildren();
  requestAnimationFrame(() => updateHomeRailNavigation(track));
  if (!entries.length) {
    if (!state.home.loading) {
      const empty = document.createElement("span");
      empty.className = "home-rail-empty";
      empty.textContent = "Noch keine Titel aus den aktiven Quellen verfügbar.";
      track.appendChild(empty);
      return;
    }
    for (let index = 0; index < 6; index += 1) {
      const skeleton = document.createElement("span");
      skeleton.className = "home-card-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      track.appendChild(skeleton);
    }
    return;
  }
  entries.forEach((entry, index) => {
    const eagerCount = ranked ? 5 : 3;
    track.appendChild(createHomeCard(entry, ranked ? index + 1 : 0, index < eagerCount));
  });
}

function renderHome() {
  state.home.discoveryDay = localDateKey();
  const profile = loadDiscoveryProfile();
  const favoriteGenre = favoriteDiscoveryGenre(profile);
  const personalTitle = document.getElementById("home-movies-title");
  const genreTitle = document.getElementById("home-genre-title");
  const genreEyebrow = document.getElementById("home-genre-eyebrow");
  if (personalTitle) {
    personalTitle.textContent = profile.interactions >= 2 ? "Für dich ausgewählt" : "Heute für dich";
  }
  if (genreTitle) {
    genreTitle.textContent = favoriteGenre ? `Weil dir ${favoriteGenre} gefällt` : "Genres zum Entdecken";
  }
  if (genreEyebrow) {
    genreEyebrow.textContent = favoriteGenre ? "Aus deinen Klicks und Downloads" : "Zum Kennenlernen";
  }
  renderHomeHero();
  renderHomeRail("home-top-track", homeTopEntries(), { ranked: true });
  renderHomeRail("home-movies-track", homePersonalizedEntries());
  renderHomeRail("home-series-track", homePopularSeriesEntries());
  renderHomeRail("home-genre-track", homeGenreEntries());
  renderHomeRail("home-explore-track", homeExploreEntries());
  renderHomeRail("home-gems-track", homeGemEntries());
  renderHomeRail("home-new-track", homeNewEntries());
  scheduleHomeHeroRotation();
}

const SEARCH_HISTORY_KEY = "royal-search-history-v1";
const HOME_CACHE_KEY = "royal-home-cache-v2";
const HOME_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function restoreHomeCache() {
  try {
    const cached = JSON.parse(localStorage.getItem(HOME_CACHE_KEY) || "null");
    if (
      !cached
      || Date.now() - Number(cached.savedAt || 0) > HOME_CACHE_MAX_AGE_MS
      || !cached.home
    ) return false;
    const keys = [
      "newMovies", "topMovies", "trendingSeries", "newSeries",
      "discoveryMovies", "discoverySeries",
    ];
    if (!keys.some((key) => Array.isArray(cached.home[key]) && cached.home[key].length)) return false;
    keys.forEach((key) => {
      state.home[key] = Array.isArray(cached.home[key]) ? cached.home[key] : [];
    });
    Object.assign(state.fp.metadataCache, cached.movieMetadata || {});
    state.home.loading = false;
    renderHome();
    return true;
  } catch {
    return false;
  }
}

function saveHomeCache() {
  try {
    const movieSlugs = new Set([
      ...state.home.newMovies,
      ...state.home.topMovies,
      ...state.home.discoveryMovies,
    ].map((item) => item?.slug).filter(Boolean));
    const movieMetadata = Object.fromEntries(
      [...movieSlugs]
        .filter((slug) => state.fp.metadataCache[slug])
        .map((slug) => [slug, state.fp.metadataCache[slug]]),
    );
    localStorage.setItem(HOME_CACHE_KEY, JSON.stringify({
      savedAt: Date.now(),
      home: {
        newMovies: state.home.newMovies,
        topMovies: state.home.topMovies,
        trendingSeries: state.home.trendingSeries,
        newSeries: state.home.newSeries,
        discoveryMovies: state.home.discoveryMovies,
        discoverySeries: state.home.discoverySeries,
      },
      movieMetadata,
    }));
  } catch {
    // Ein voller oder gesperrter Browser-Speicher darf die Startseite nicht blockieren.
  }
}

function searchHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(SEARCH_HISTORY_KEY) || "[]");
    return Array.isArray(value) ? value.filter((entry) => entry?.query).slice(0, 6) : [];
  } catch {
    return [];
  }
}

function rememberSearch(query, kind) {
  const normalized = query.trim();
  if (!normalized) return;
  const next = [
    { query: normalized, kind },
    ...searchHistory().filter((entry) => entry.query.toLocaleLowerCase() !== normalized.toLocaleLowerCase()),
  ].slice(0, 6);
  try {
    localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(next));
  } catch {
    // Private Modi können lokalen Speicher blockieren; die Suche bleibt nutzbar.
  }
  const matchingGenre = [...document.querySelectorAll("#genre-filter [data-genre]")]
    .map((element) => element.dataset.genre || "")
    .find((genre) => genre && genre !== "Alle Genres"
      && genre.localeCompare(normalized, "de", { sensitivity: "base" }) === 0);
  api.tasteEvent({
    action: "search", source: "web", media_type: kind, query: normalized,
    metadata: matchingGenre ? { genres: [matchingGenre] } : {},
  }).catch((error) => console.warn("Suchsignal konnte nicht gespeichert werden:", error));
}

function searchCandidates(kind) {
  const movies = uniqueHomeEntries([
    ...state.fp.results.map(homeMovieEntry),
    ...state.home.topMovies.map(homeMovieEntry),
    ...state.home.newMovies.map(homeMovieEntry),
    ...state.home.discoveryMovies.map(homeMovieEntry),
  ]);
  const series = uniqueHomeEntries([
    ...state.series.results.map(homeSeriesEntry),
    ...state.home.trendingSeries.map(homeSeriesEntry),
    ...state.home.newSeries.map(homeSeriesEntry),
    ...state.home.discoverySeries.map(homeSeriesEntry),
  ]);
  if (kind === "movie") return movies;
  if (kind === "series") return series;
  return interleaveHomeEntries(movies, series, 40);
}

function searchEntryText(entry) {
  const item = entry.item;
  return [
    item.title,
    item.year,
    ...(item.genres || []),
    ...(item.actors || item.cast || []),
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}

function rankedSearchCandidates(kind, query) {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return [];
  return searchCandidates(kind)
    .map((entry) => {
      const title = String(entry.item.title || "").toLocaleLowerCase();
      const text = searchEntryText(entry);
      const score = title === needle ? 0 : title.startsWith(needle) ? 1 : title.includes(needle) ? 2 : text.includes(needle) ? 3 : 99;
      return { entry, score };
    })
    .filter(({ score }) => score < 99)
    .sort((a, b) => a.score - b.score || String(a.entry.item.title).localeCompare(String(b.entry.item.title), "de"))
    .slice(0, 6)
    .map(({ entry }) => entry);
}

function closeSearchSuggestions(panelId, inputId) {
  const panel = document.getElementById(panelId);
  const input = document.getElementById(inputId);
  if (panel) panel.hidden = true;
  if (input) input.setAttribute("aria-expanded", "false");
}

function renderSearchSuggestions(kind, inputId, panelId, runSearch) {
  const input = document.getElementById(inputId);
  const panel = document.getElementById(panelId);
  if (!input || !panel) return;
  const query = input.value.trim();
  const matches = rankedSearchCandidates(kind, query);
  const recent = query ? [] : searchHistory().filter((entry) => kind === "all" || entry.kind === kind).slice(0, 4);
  panel.replaceChildren();
  const rows = matches.length
    ? matches.map((entry) => ({
        label: entry.item.title,
        meta: `${entry.kind === "movie" ? "Film" : "Serie"}${entry.item.year ? ` · ${entry.item.year}` : ""}`,
      }))
    : recent.map((entry) => ({ label: entry.query, meta: "Zuletzt gesucht" }));
  if (!rows.length) {
    closeSearchSuggestions(panelId, inputId);
    return;
  }
  const heading = document.createElement("span");
  heading.className = "smart-search-suggestions-label";
  heading.textContent = matches.length ? "Direkte Treffer" : "Letzte Suchen";
  panel.appendChild(heading);
  rows.forEach((row) => {
    const button = document.createElement("button");
    button.type = "button";
    const label = document.createElement("strong");
    label.textContent = row.label;
    const meta = document.createElement("span");
    meta.textContent = row.meta;
    button.append(label, meta);
    button.addEventListener("click", () => {
      input.value = row.label;
      syncSearchClearButtons();
      closeSearchSuggestions(panelId, inputId);
      runSearch();
    });
    panel.appendChild(button);
  });
  panel.hidden = false;
  input.setAttribute("aria-expanded", "true");
}

function syncSearchClearButtons() {
  [
    ["home-search", "home-search-clear"],
    ["fp-search", "fp-search-clear"],
    ["series-search", "series-search-clear"],
  ].forEach(([inputId, clearId]) => {
    const input = document.getElementById(inputId);
    const clear = document.getElementById(clearId);
    if (input && clear) clear.hidden = !input.value;
  });
}

function renderGlobalSearchResults() {
  const page = document.getElementById("global-search-page");
  const grid = document.getElementById("global-search-grid");
  const status = document.getElementById("global-search-status");
  const shell = document.getElementById("global-search-shell");
  const input = document.getElementById("global-search-input");
  const clear = document.getElementById("global-search-clear");
  const toggle = document.getElementById("global-search-toggle");
  if (!page || !grid || !status || !shell || !input || !clear || !toggle) return;

  page.hidden = !state.globalSearch.active;
  document.body.classList.toggle("global-search-open", state.globalSearch.active);
  shell.classList.toggle("has-value", Boolean(input.value));
  clear.hidden = !input.value;
  toggle.setAttribute("aria-expanded", String(state.globalSearch.active || document.activeElement === input));
  input.setAttribute("aria-expanded", String(state.globalSearch.active));
  if (!state.globalSearch.active) return;

  grid.replaceChildren();
  const visibleResults = state.globalSearch.results.filter((entry) => {
    const scopeMatches = state.globalSearch.scope === "all" || entry.kind === state.globalSearch.scope;
    const libraryMatches = !state.globalSearch.jellyfinOnly || mediaJellyfinStatus(entry.item) === "owned";
    return scopeMatches && libraryMatches;
  });
  document.querySelectorAll("[data-global-search-scope]").forEach((button) => {
    const active = button.dataset.globalSearchScope === state.globalSearch.scope;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const libraryFilter = document.getElementById("global-search-jellyfin");
  if (libraryFilter) {
    libraryFilter.classList.toggle("is-active", state.globalSearch.jellyfinOnly);
    libraryFilter.setAttribute("aria-pressed", String(state.globalSearch.jellyfinOnly));
  }
  const jellyfinCount = state.globalSearch.results.filter(
    (entry) => mediaJellyfinStatus(entry.item) === "owned",
  ).length;
  status.textContent = !state.globalSearch.submitted
    ? "Enter drücken, um alle Kataloge zu durchsuchen."
    : state.globalSearch.loading
    ? `Suche nach «${state.globalSearch.query}» …`
    : `${visibleResults.length} Treffer · ${jellyfinCount} davon in Jellyfin`;
  page.classList.toggle("is-loading", state.globalSearch.loading);
  if (state.globalSearch.loading) {
    for (let index = 0; index < 12; index += 1) {
      const skeleton = document.createElement("span");
      skeleton.className = "home-card-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      grid.appendChild(skeleton);
    }
    return;
  }
  if (!visibleResults.length) {
    const empty = document.createElement("div");
    empty.className = "global-search-empty";
    empty.innerHTML = state.globalSearch.submitted
      ? "<strong>Nichts in diesem Filter</strong><span>Filter ändern oder einen anderen Titel suchen.</span>"
      : "<strong>Bereit zum Suchen</strong><span>Suchbegriff prüfen und Enter drücken.</span>";
    grid.appendChild(empty);
    return;
  }
  visibleResults.forEach((entry, index) => {
    grid.appendChild(createHomeCard(entry, 0, index < 8));
  });
}

async function performGlobalSearch(query, requestId) {
  rememberSearch(query, "all");
  const settled = await Promise.allSettled([
    api.movies({ mode: "search", query }).then((data) => (data.results || []).map(homeMovieEntry)),
    api.series({ mode: "search", query }).then((data) => (data.results || []).map(homeSeriesEntry)),
    api.anime({ mode: "search", query, page: 1 }).then((data) => (data.results || []).map(homeAnimeEntry)),
  ]);
  if (requestId !== state.globalSearch.requestSeq) return;
  const groups = settled
    .filter((result) => result.status === "fulfilled")
    .map((result) => result.value);
  const mixed = [];
  const max = Math.max(0, ...groups.map((group) => group.length));
  for (let index = 0; index < max && mixed.length < 60; index += 1) {
    groups.forEach((group) => {
      if (group[index] && mixed.length < 60) mixed.push(group[index]);
    });
  }
  state.globalSearch.results = uniqueHomeEntries(mixed).slice(0, 60);
  state.globalSearch.loading = false;
  renderGlobalSearchResults();
  await Promise.allSettled([
    hydrateHomeMovieArtwork(
      state.globalSearch.results
        .filter((entry) => entry.kind === "movie")
        .map((entry) => entry.item),
      { render: false },
    ),
    hydrateHomeSeriesArtwork(
      state.globalSearch.results
        .filter((entry) => entry.kind === "series")
        .map((entry) => entry.item),
      { render: false },
    ),
    refreshCatalogJellyfinStatus(state.globalSearch.results, null),
  ]);
  if (requestId !== state.globalSearch.requestSeq) return;
  renderGlobalSearchResults();
}

function syncGlobalSearchDraft() {
  const query = document.getElementById("global-search-input")?.value.trim() || "";
  ++state.globalSearch.requestSeq;
  state.globalSearch.query = query;
  state.globalSearch.active = Boolean(query);
  state.globalSearch.loading = false;
  state.globalSearch.submitted = false;
  state.globalSearch.results = [];
  renderGlobalSearchResults();
}

function runGlobalSearch() {
  const input = document.getElementById("global-search-input");
  const query = input.value.trim();
  const requestId = ++state.globalSearch.requestSeq;
  state.globalSearch.query = query;
  if (!query) {
    state.globalSearch.active = false;
    state.globalSearch.loading = false;
    state.globalSearch.submitted = false;
    state.globalSearch.results = [];
    renderGlobalSearchResults();
    return;
  }
  state.globalSearch.active = true;
  state.globalSearch.loading = true;
  state.globalSearch.submitted = true;
  state.globalSearch.results = [];
  renderGlobalSearchResults();
  void performGlobalSearch(query, requestId);
}

function closeGlobalSearch({ restoreFocus = false } = {}) {
  const input = document.getElementById("global-search-input");
  if (!input) return;
  ++state.globalSearch.requestSeq;
  state.globalSearch.query = "";
  state.globalSearch.results = [];
  state.globalSearch.active = false;
  state.globalSearch.loading = false;
  state.globalSearch.submitted = false;
  input.value = "";
  renderGlobalSearchResults();
  if (restoreFocus) document.getElementById("global-search-toggle")?.focus();
}

function renderHomeSearchResults() {
  const section = document.getElementById("home-search-results");
  const track = document.getElementById("home-search-track");
  const status = document.getElementById("home-search-status");
  if (!section || !track || !status) return;
  section.hidden = !state.home.search.active;
  if (!state.home.search.active) return;
  track.replaceChildren();
  status.textContent = state.home.search.loading
    ? `Suche nach «${state.home.search.query}» …`
    : `${state.home.search.results.length} Treffer für «${state.home.search.query}»`;
  section.classList.toggle("is-loading", state.home.search.loading);
  if (state.home.search.loading) {
    for (let index = 0; index < 6; index += 1) {
      const skeleton = document.createElement("span");
      skeleton.className = "home-card-skeleton";
      track.appendChild(skeleton);
    }
    return;
  }
  if (!state.home.search.results.length) {
    const empty = document.createElement("div");
    empty.className = "home-search-empty";
    empty.innerHTML = "<strong>Nichts gefunden</strong><span>Versuche einen kürzeren Titel, ein Genre oder einen Schauspieler.</span>";
    track.appendChild(empty);
    return;
  }
  state.home.search.results.forEach((entry, index) => track.appendChild(createHomeCard(entry, 0, index < 4)));
}

async function homeSearch() {
  const input = document.getElementById("home-search");
  const query = input.value.trim();
  if (!query) {
    closeSearchSuggestions("home-search-suggestions", "home-search");
    return;
  }
  rememberSearch(query, state.home.search.scope);
  closeSearchSuggestions("home-search-suggestions", "home-search");
  const requestId = ++state.home.search.requestSeq;
  state.home.search.query = query;
  state.home.search.active = true;
  state.home.search.loading = true;
  renderHomeSearchResults();
  const requests = [];
  if (state.home.search.scope !== "series") {
    requests.push(api.movies({ mode: "search", query }).then((data) => (data.results || []).map(homeMovieEntry)));
  }
  if (state.home.search.scope !== "movie") {
    requests.push(api.series({ mode: "search", query }).then((data) => (data.results || []).map(homeSeriesEntry)));
  }
  const settled = await Promise.allSettled(requests);
  if (requestId !== state.home.search.requestSeq) return;
  const groups = settled.filter((result) => result.status === "fulfilled").map((result) => result.value);
  state.home.search.results = groups.length > 1
    ? interleaveHomeEntries(groups[0], groups[1], 36)
    : uniqueHomeEntries(groups[0] || []).slice(0, 36);
  state.home.search.loading = false;
  renderHomeSearchResults();
  await Promise.allSettled([
    hydrateHomeMovieArtwork(
      state.home.search.results.filter((entry) => entry.kind === "movie").map((entry) => entry.item),
      { render: false },
    ),
    hydrateHomeSeriesArtwork(
      state.home.search.results.filter((entry) => entry.kind === "series").map((entry) => entry.item),
      { render: false },
    ),
  ]);
  await refreshCatalogJellyfinStatus(state.home.search.results, null);
  if (requestId === state.home.search.requestSeq) renderHomeSearchResults();
}

function closeHomeSearch() {
  ++state.home.search.requestSeq;
  state.home.search.active = false;
  state.home.search.loading = false;
  state.home.search.results = [];
  document.getElementById("home-search").value = "";
  syncSearchClearButtons();
  renderHomeSearchResults();
}

async function loadHomeData() {
  state.home.loading = true;
  if (!homeAllEntries().length) renderHome();
  const newMoviesRequest = api.movies({ mode: "new", page: 1 });
  const trendingSeriesRequest = api.series({ mode: "trending", page: 1 });
  const topMoviesRequest = api.movies({ mode: "top", page: 1 });
  const newSeriesRequest = api.series({ mode: "new", page: 1 });
  const discoveryMoviesRequest = Promise.allSettled([
    api.movies({ mode: "new", page: 2 }),
    api.movies({ mode: "top", page: 2 }),
  ]).then((results) => {
    return results
      .filter((result) => result.status === "fulfilled")
      .flatMap((result) => result.value.results || []);
  });
  const discoverySeriesRequest = api.series({ mode: "discover", page: 1 });
  const results = await Promise.allSettled([
    newMoviesRequest,
    trendingSeriesRequest,
    topMoviesRequest,
    newSeriesRequest,
    discoveryMoviesRequest,
    discoverySeriesRequest,
  ]);
  if (results[0].status === "fulfilled") state.home.newMovies = results[0].value.results || [];
  if (results[1].status === "fulfilled") state.home.trendingSeries = results[1].value.results || [];
  if (results[2].status === "fulfilled") state.home.topMovies = results[2].value.results || [];
  if (results[3].status === "fulfilled") state.home.newSeries = results[3].value.results || [];
  if (results[4].status === "fulfilled" && results[4].value.length) {
    state.home.discoveryMovies = results[4].value;
  }
  if (results[5].status === "fulfilled") state.home.discoverySeries = results[5].value.results || [];
  if (!state.home.topMovies.length) state.home.topMovies = state.home.newMovies.slice();
  if (!state.home.newSeries.length) state.home.newSeries = state.home.trendingSeries.slice();
  renderHome();
  await Promise.allSettled([
    hydrateHomeMovieArtwork([
      ...state.home.newMovies,
      ...state.home.topMovies,
      ...state.home.discoveryMovies,
    ], { render: false }),
    hydrateHomeSeriesArtwork([
      ...state.home.trendingSeries,
      ...state.home.newSeries,
      ...state.home.discoverySeries,
    ], { render: false }),
  ]);
  await refreshCatalogJellyfinStatus(homeAllEntries(), null);
  state.home.loading = false;
  saveHomeCache();
  renderHome();
}

async function hydrateHomeMovieArtwork(items, { render = true } = {}) {
  const targets = [
    ...new Map(
      items
        .filter((item) => {
          if (!item?.slug) return false;
          const known = { ...item, ...(state.fp.metadataCache[item.slug] || {}) };
          return !known.cover_url || !known.backdrop_url;
        })
        .map((item) => [item.slug, item]),
    ).values(),
  ];
  if (!targets.length) return;
  try {
    const response = await api.tmdbMovies(targets.map((item) => ({
      slug: item.slug,
      title: item.title,
      year: item.year || "",
    })));
    for (const [slug, metadata] of Object.entries(response.movies || {})) {
      if (metadata) {
        state.fp.metadataCache[slug] = { ...(state.fp.metadataCache[slug] || {}), ...metadata };
      }
    }
    if (render) renderHome();
  } catch (error) {
    console.warn("Startseitenbilder konnten nicht ergänzt werden:", error);
  }
}

async function hydrateHomeSeriesArtwork(items, { render = true } = {}) {
  const targets = [
    ...new Map(
      items
        .filter((item) => item?.base_slug && (!item.cover_url || !item.backdrop_url))
        .map((item) => [item.base_slug, item]),
    ).values(),
  ];
  if (!targets.length) return [];
  const hydratedBaseSlugs = [];
  try {
    const response = await api.tmdbSeries(targets.map((item) => ({
      base_slug: item.base_slug,
      title: item.title,
      year: item.year || "",
    })));
    for (const item of targets) {
      const metadata = response.series?.[item.base_slug];
      if (!metadata) continue;
      const hadCover = Boolean(item.cover_url);
      const hadBackdrop = Boolean(item.backdrop_url);
      Object.assign(item, metadata, {
        cover_url: metadata.cover_url || item.cover_url || "",
        backdrop_url: metadata.backdrop_url || item.backdrop_url || "",
      });
      if ((!hadCover && item.cover_url) || (!hadBackdrop && item.backdrop_url)) {
        hydratedBaseSlugs.push(item.base_slug);
      }
    }
    if (render) renderHome();
  } catch (error) {
    console.warn("Serien-Wallpaper konnten nicht ergänzt werden:", error);
  }
  return hydratedBaseSlugs;
}
