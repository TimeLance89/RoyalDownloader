import { createScope } from "../../core/lifecycle.js";

/** Movie discovery billboard. Rotation, focus and selection belong to this view. */
export function createMovieHero(root, { getCatalog, getProviderLabels, coverUrl, locale, openMovie, onUpdateHome }) {
  const local = { candidates: [], index: 0, paused: false };
  let scope;
  let rows;
  let stopRotation;
  const find = id => root.querySelector(`#${id}`);
  // ── Filme-Tab ──────────────────────────────────────────────────────────────
  const MOVIE_FEATURE_INTERVAL_MS = 9000;
  const MOVIE_FEATURE_MAX_AGE_DAYS = 270;
  const MOVIE_FEATURE_MAX_FUTURE_DAYS = 45;
  function movieFeatureCandidate(result) {
    const metadata = getCatalog().metadataCache[result.slug] || {};
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
    stopRotation?.(); stopRotation = null;
  }

  function scheduleMovieFeatureRotation() {
    stopMovieFeatureRotation();
    if (!scope?.active) return;
    const feature = root;
    if (
      !feature
      || feature.classList.contains("hidden")
      || local.paused
      || local.candidates.length < 2
      || feature.matches(":hover")
      || feature.contains(document.activeElement)
      || document.hidden
      || window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) return;
    stopRotation = scope.interval(() => {
      showMovieFeature(local.index + 1);
    }, MOVIE_FEATURE_INTERVAL_MS);
  }

  function setMovieFeaturePaused(paused) {
    local.paused = paused;
    const button = find("movie-feature-pause");
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
    return date.toLocaleDateString(locale(), {
      day: "2-digit", month: "short", year: "numeric",
    });
  }

  function renderMovieFeature() {
    if (!scope?.active) return;
    rows?.dispose(); rows = createScope();
    const feature = root;
    const candidates = local.candidates;
    const candidate = candidates[local.index];
    if (!feature || !candidate) {
      feature?.classList.add("hidden");
      stopMovieFeatureRotation();
      return;
    }

    feature.classList.remove("hidden");
    feature.classList.toggle("is-poster-art", candidate.artworkKind === "poster");
    feature.classList.toggle("has-no-art", candidate.artworkKind === "none");
    feature.setAttribute("aria-label", `Aktuelle Kinofilme: ${candidate.title}`);
    find("movie-feature-art").style.backgroundImage = candidate.artwork
      ? `url("${coverUrl(candidate.artwork).replace(/"/g, "%22")}")`
      : "";
    find("movie-feature-title").textContent = candidate.title;
    find("movie-feature-count").textContent =
      `${local.index + 1} / ${candidates.length}`;
    find("movie-feature-description").textContent =
      candidate.description || "Neu bei deinen ausgewählten Filmquellen.";
    const provider = getProviderLabels()[candidate.provider] || "";
    find("movie-feature-meta").textContent = [
      movieFeatureDate(candidate),
      candidate.rating ? `★ ${candidate.rating}` : "",
      ...(candidate.genres || []).slice(0, 2),
      provider,
    ].filter(Boolean).join(" · ");
    find("movie-feature-open").dataset.slug = candidate.slug;

    const dots = find("movie-feature-dots");
    dots.innerHTML = "";
    candidates.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = index === local.index ? "is-active" : "";
      button.setAttribute("aria-label", `${item.title} anzeigen`);
      button.setAttribute("aria-pressed", String(index === local.index));
      rows.listen(button, "click", () => {
        showMovieFeature(index, true);
        scheduleMovieFeatureRotation();
      });
      dots.appendChild(button);
    });
  }

  function showMovieFeature(index, userInitiated = false) {
    const count = local.candidates.length;
    if (!count) return;
    local.index = ((index % count) + count) % count;
    const feature = root;
    if (!userInitiated && feature) {
      feature.classList.add("is-changing");
      scope.timeout(() => feature.classList.remove("is-changing"), 360);
    }
    renderMovieFeature();
  }

  function refreshMovieFeatureCandidates() {
    if (!scope?.active) { onUpdateHome(); return; }
    if (getCatalog().category !== "new") {
      root?.classList.add("hidden");
      stopMovieFeatureRotation();
      return;
    }
    const currentSlug = local.candidates[local.index]?.slug;
    const seenTitles = new Set();
    const allCandidates = getCatalog().results
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
    local.candidates = candidates;
    const preservedIndex = candidates.findIndex((candidate) => candidate.slug === currentSlug);
    local.index = preservedIndex >= 0 ? preservedIndex : 0;
    renderMovieFeature();
    scheduleMovieFeatureRotation();
    onUpdateHome();
  }

  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.listen(find("movie-feature-open"), "click", event => {
        const slug = event.currentTarget.dataset.slug;
        if (slug) openMovie(slug);
      });
      scope.listen(find("movie-feature-prev"), "click", () => { showMovieFeature(local.index - 1, true); scheduleMovieFeatureRotation(); });
      scope.listen(find("movie-feature-next"), "click", () => { showMovieFeature(local.index + 1, true); scheduleMovieFeatureRotation(); });
      scope.listen(find("movie-feature-pause"), "click", () => setMovieFeaturePaused(!local.paused));
      scope.listen(root, "pointerenter", stopMovieFeatureRotation);
      scope.listen(root, "pointerleave", scheduleMovieFeatureRotation);
      scope.listen(root, "focusin", stopMovieFeatureRotation);
      scope.listen(root, "focusout", () => scope.timeout(() => { if (!root.contains(document.activeElement)) scheduleMovieFeatureRotation(); }, 0));
      scope.listen(document, "visibilitychange", () => document.hidden ? stopMovieFeatureRotation() : scheduleMovieFeatureRotation());
      refreshMovieFeatureCandidates();
    },
    refresh: refreshMovieFeatureCandidates,
    unmount() {
      stopMovieFeatureRotation(); rows?.dispose(); rows = null; scope?.dispose(); scope = null;
      root.classList.remove("is-changing");
    },
  };
}
