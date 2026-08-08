/* Royal Home Experience v2: informative card hover + taste-ranked hero. */
(() => {
  "use strict";

  if (window.__royalHomeExperienceV2Installed) return;

  const HERO_LIMIT = 7;
  const HERO_STRONG_TARGET = 5;
  const HERO_MIN_RATING = 5.5;
  const HERO_MAX_SAME_KIND = 4;
  const HERO_MAX_OWNED = 4;
  const MATCH_FACTORS = {
    genres: 1.00,
    tags: 0.72,
    studios: 0.34,
    directors: 0.82,
    actors: 0.46,
    languages: 0.18,
    decades: 0.28,
    runtime_buckets: 0.18,
    media_types: 0.46,
    franchises: 0.74,
  };
  const GENRE_ALIASES = new Map(Object.entries({
    action: "Action",
    adventure: "Abenteuer",
    abenteuer: "Abenteuer",
    animation: "Animation",
    anime: "Anime",
    comedy: "Komödie",
    komodie: "Komödie",
    drama: "Drama",
    family: "Familie",
    familie: "Familie",
    fantasy: "Fantasy",
    history: "Geschichte",
    geschichte: "Geschichte",
    horror: "Horror",
    crime: "Krimi",
    krimi: "Krimi",
    music: "Musik",
    musik: "Musik",
    mystery: "Mystery",
    romance: "Romanze",
    romanze: "Romanze",
    sciencefiction: "Science-Fiction",
    scifi: "Science-Fiction",
    thriller: "Thriller",
    war: "Krieg",
    krieg: "Krieg",
    western: "Western",
    documentary: "Dokumentation",
    dokumentation: "Dokumentation",
    dokumentarfilm: "Dokumentation",
  }));

  function normalizeToken(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/gi, "")
      .toLowerCase();
  }

  function canonicalValue(dimension, value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (dimension === "genres") return GENRE_ALIASES.get(normalizeToken(text)) || text;
    if (dimension === "media_types") {
      const token = normalizeToken(text);
      if (["movie", "film"].includes(token)) return "movie";
      if (["series", "serie", "tv"].includes(token)) return "series";
      return token;
    }
    if (dimension === "languages") {
      const token = normalizeToken(text);
      if (["de", "deu", "ger", "german", "deutsch"].includes(token)) return "de";
      if (["en", "eng", "english", "englisch"].includes(token)) return "en";
    }
    return text;
  }

  function canonicalValues(dimension, values) {
    const source = Array.isArray(values) ? values : (values ? [values] : []);
    const result = [];
    const seen = new Set();
    for (const raw of source) {
      const candidate = raw && typeof raw === "object"
        ? (raw.name || raw.Name || raw.title || raw.Title || "")
        : raw;
      const value = canonicalValue(dimension, candidate);
      const key = value.toLocaleLowerCase();
      if (value && !seen.has(key)) {
        seen.add(key);
        result.push(value);
      }
      if (result.length >= 12) break;
    }
    return result;
  }

  function logicalKey(entry) {
    if (typeof discoveryV2LogicalKey === "function") return discoveryV2LogicalKey(entry);
    return typeof homeEntryKey === "function" ? homeEntryKey(entry) : "";
  }

  function entryMedia(entry) {
    return typeof homeEntryMedia === "function" ? homeEntryMedia(entry) : (entry?.item || {});
  }

  function heroMetadata(entry) {
    const media = entryMedia(entry);
    const base = typeof tasteMetadata === "function" ? tasteMetadata(entry.kind, media) : {};
    const year = Number(String(base.year || media.year || media.first_air_date || "").slice(0, 4));
    let runtime = Number(String(base.runtime || media.runtime || "").match(/\d+(?:[.,]\d+)?/)?.[0]?.replace(",", ".") || 0);
    if (!Number.isFinite(runtime)) runtime = 0;
    const franchises = [
      media.franchise,
      media.collection?.name || media.collection,
      media.belongs_to_collection?.name || media.belongs_to_collection,
      media.series_name,
    ].filter(Boolean);
    return {
      genres: canonicalValues("genres", base.genres || media.genres || []),
      tags: canonicalValues("tags", base.tags || media.tags || media.keywords || []),
      studios: canonicalValues("studios", base.studios || media.studios || media.production_companies || []),
      directors: canonicalValues("directors", base.directors || media.directors || []),
      actors: canonicalValues("actors", base.actors || media.actors || media.cast || []),
      languages: canonicalValues("languages", base.languages || media.languages || media.spoken_languages || []),
      franchises: canonicalValues("franchises", franchises),
      decades: year ? [`${Math.floor(year / 10) * 10}er`] : [],
      runtime_buckets: runtime > 0 ? [runtime < 45 ? "kurz" : runtime < 100 ? "mittel" : "lang"] : [],
      media_types: [canonicalValue("media_types", entry.kind)],
    };
  }

  function profileLookup(profile, dimension) {
    const lookup = new Map();
    Object.entries(profile?.dimensions?.[dimension] || {}).forEach(([name, score]) => {
      const numeric = Number(score);
      if (Number.isFinite(numeric)) lookup.set(String(name).toLocaleLowerCase(), { name, score: numeric });
    });
    return lookup;
  }

  function heroTasteScore(entry, profile) {
    const metadata = heroMetadata(entry);
    const policy = profile?.ranking || {};
    const negativeMultiplier = Number(policy.negative_multiplier ?? 1.55);
    const confidence = Math.max(0, Math.min(1, Number(profile?.confidence || 0)));
    let positive = 0;
    let negative = 0;
    let known = 0;
    let total = 0;
    const reasons = [];

    Object.entries(metadata).forEach(([dimension, values]) => {
      const factor = MATCH_FACTORS[dimension];
      if (!factor || !values.length) return;
      total += values.length;
      const lookup = profileLookup(profile, dimension);
      const hits = values.map((value) => lookup.get(String(value).toLocaleLowerCase())).filter(Boolean);
      known += hits.length;
      if (!hits.length) return;
      const divisor = Math.sqrt(Math.max(1, values.length));
      hits.forEach((hit) => {
        let contribution = factor * hit.score / divisor;
        if (contribution < 0) contribution *= negativeMultiplier;
        if (contribution >= 0) positive += contribution;
        else negative += contribution;
        reasons.push({ value: hit.name, contribution });
      });
    });

    const genreLookup = profileLookup(profile, "genres");
    const unknownGenres = metadata.genres.filter(
      (value) => !genreLookup.has(String(value).toLocaleLowerCase()),
    );
    const confidenceFloor = Number(policy.unknown_genre_confidence_floor ?? 0.55);
    const unknownPenalty = confidence >= confidenceFloor && metadata.genres.length >= 2
      ? Math.min(4.5, unknownGenres.length * Number(policy.unknown_genre_penalty ?? 1.35) * confidence)
      : 0;
    const media = entryMedia(entry);
    const rating = Number(media.rating || 0);
    const votes = Number(media.vote_count || 0);
    const exposure = typeof discoveryV2ExposurePenalty === "function"
      ? Number(discoveryV2ExposurePenalty(entry, "hero") || 0)
      : 0;
    const score = positive
      + negative
      - unknownPenalty
      - exposure * 0.72
      + rating * 0.13
      + Math.min(1.6, Math.log10(votes + 1) * 0.34);
    const coverage = total ? known / total : 0;
    reasons.sort((left, right) => Math.abs(right.contribution) - Math.abs(left.contribution));
    return {
      score,
      positive,
      negative,
      coverage,
      exposure,
      reasons: reasons.slice(0, 5),
    };
  }

  function heroTrendRanks() {
    const result = new Map();
    const add = (entry, index, lane) => {
      const key = logicalKey(entry);
      if (!key || result.has(key)) return;
      result.set(key, { index, lane });
    };
    (state.home.topMovies || []).forEach((item, index) => add(homeMovieEntry(item), index, "movie-top"));
    (state.home.trendingSeries || []).forEach((item, index) => add(homeSeriesEntry(item), index, "series-trending"));
    return result;
  }

  function favoriteHeroGenres(profile) {
    return new Set(Object.entries(profile?.genres || {})
      .filter(([, score]) => Number(score) > 0)
      .sort((left, right) => Number(right[1]) - Number(left[1]))
      .slice(0, 2)
      .map(([name]) => normalizeToken(canonicalValue("genres", name))));
  }

  function hasHeroBackdrop(entry) {
    return Boolean(entryMedia(entry).backdrop_url);
  }

  function heroRatingOkay(entry) {
    const rating = Number(entryMedia(entry).rating || 0);
    return !rating || rating >= HERO_MIN_RATING;
  }

  function isOwned(entry) {
    try {
      return typeof mediaJellyfinStatus === "function"
        && mediaJellyfinStatus(entryMedia(entry)) === "owned";
    } catch {
      return false;
    }
  }

  function heroRecord(entry, profile, trendRanks) {
    const taste = heroTasteScore(entry, profile);
    const media = entryMedia(entry);
    const trend = trendRanks.get(logicalKey(entry));
    const rating = Number(media.rating || 0);
    const votes = Number(media.vote_count || 0);
    const trendBonus = trend ? Math.max(0, 5.5 - trend.index * 0.38) : 0;
    return {
      entry,
      ...taste,
      trend,
      rankingScore: taste.score
        + trendBonus
        + rating * 0.18
        + Math.min(2.2, Math.log10(votes + 1) * 0.42),
    };
  }

  function addBalanced(selected, selectedKeys, records, targetCount, { relax = false } = {}) {
    const kindCounts = new Map();
    let ownedCount = 0;
    selected.forEach((entry) => {
      kindCounts.set(entry.kind, Number(kindCounts.get(entry.kind) || 0) + 1);
      if (isOwned(entry)) ownedCount += 1;
    });
    for (const record of records) {
      if (selected.length >= targetCount) break;
      const entry = record.entry;
      const key = logicalKey(entry);
      if (!key || selectedKeys.has(key)) continue;
      const kindCount = Number(kindCounts.get(entry.kind) || 0);
      const owned = isOwned(entry);
      if (!relax && kindCount >= HERO_MAX_SAME_KIND) continue;
      if (!relax && owned && ownedCount >= HERO_MAX_OWNED) continue;
      selected.push(entry);
      selectedKeys.add(key);
      kindCounts.set(entry.kind, kindCount + 1);
      if (owned) ownedCount += 1;
    }
  }

  function tasteRankedHeroEntries() {
    const profile = loadDiscoveryProfile();
    const trained = Number(profile.interactions || 0) >= 2 && Number(profile.confidence || 0) >= 0.18;
    const trendRanks = heroTrendRanks();
    const pool = homeAllEntries();
    const blocked = new Set(profile.blocked_items || []);
    const records = pool
      .filter((entry) => {
        const direct = typeof homeEntryKey === "function" ? homeEntryKey(entry) : "";
        const logical = logicalKey(entry);
        return !blocked.has(direct) && !blocked.has(logical);
      })
      .map((entry) => heroRecord(entry, profile, trendRanks));

    const withBackdrop = records.filter(({ entry }) => hasHeroBackdrop(entry));
    const qualityPool = withBackdrop.filter(({ entry }) => heroRatingOkay(entry));
    const source = qualityPool.length >= 4 ? qualityPool : withBackdrop;
    const minAffinity = Number(profile.ranking?.personal_min_affinity ?? 1.25);
    const minCoverage = Number(profile.ranking?.personal_min_coverage ?? 0.18);
    const adjacentFloor = Number(profile.ranking?.adjacent_min_affinity ?? 0.10);

    const byTaste = source.slice().sort((left, right) =>
      right.rankingScore - left.rankingScore
      || Number(entryMedia(right.entry).rating || 0) - Number(entryMedia(left.entry).rating || 0));

    if (!trained) {
      const cold = byTaste.slice().sort((left, right) => {
        const leftTrend = left.trend ? Math.max(0, 40 - left.trend.index) : 0;
        const rightTrend = right.trend ? Math.max(0, 40 - right.trend.index) : 0;
        return rightTrend - leftTrend
          || Number(entryMedia(right.entry).rating || 0) - Number(entryMedia(left.entry).rating || 0)
          || right.rankingScore - left.rankingScore;
      });
      const selected = [];
      const selectedKeys = new Set();
      addBalanced(selected, selectedKeys, cold, HERO_LIMIT);
      addBalanced(selected, selectedKeys, cold, HERO_LIMIT, { relax: true });
      return selected;
    }

    const strong = byTaste.filter((record) =>
      record.score >= minAffinity
      && record.coverage >= minCoverage
      && record.positive > Math.abs(record.negative));
    const trend = byTaste.filter((record) =>
      record.trend
      && record.score >= Math.max(adjacentFloor, 0.35)
      && record.positive > 0
      && record.negative > -Math.max(2.5, record.positive));
    const favorites = favoriteHeroGenres(profile);
    const discovery = byTaste.filter((record) => {
      if (record.score < adjacentFloor || record.positive <= 0) return false;
      if (record.negative <= -Math.max(2.5, record.positive)) return false;
      const genres = heroMetadata(record.entry).genres.map(normalizeToken);
      return genres.length && genres.some((genre) => !favorites.has(genre));
    });

    const selected = [];
    const selectedKeys = new Set();

    // Hero v2: five strongest personal matches, one taste-compatible current
    // trend, and one adjacent discovery. No daily hash or shuffle seed is used.
    addBalanced(selected, selectedKeys, strong, HERO_STRONG_TARGET);
    addBalanced(selected, selectedKeys, trend, Math.min(HERO_LIMIT, selected.length + 1));
    addBalanced(selected, selectedKeys, discovery, Math.min(HERO_LIMIT, selected.length + 1));
    addBalanced(selected, selectedKeys, strong, HERO_LIMIT);

    const adjacent = byTaste.filter((record) =>
      record.score >= adjacentFloor
      && record.positive > 0
      && record.negative > -Math.max(2.5, record.positive));
    addBalanced(selected, selectedKeys, adjacent, HERO_LIMIT);
    addBalanced(selected, selectedKeys, adjacent, HERO_LIMIT, { relax: true });
    return selected.slice(0, HERO_LIMIT);
  }

  function homeExperienceHeroCandidates() {
    let entries = tasteRankedHeroEntries();
    if (entries.length < 2) {
      // Artwork may still be hydrating during first paint. Stay taste-first, but
      // permit the existing poster fallback rather than leaving the hero empty.
      const profile = loadDiscoveryProfile();
      const trendRanks = heroTrendRanks();
      const selectedKeys = new Set(entries.map(logicalKey));
      const fallback = homeAllEntries()
        .filter((entry) => !selectedKeys.has(logicalKey(entry)))
        .map((entry) => heroRecord(entry, profile, trendRanks))
        .filter(({ entry }) => Boolean(entryMedia(entry).backdrop_url || entryMedia(entry).cover_url))
        .sort((left, right) => right.rankingScore - left.rankingScore);
      entries = [...entries, ...fallback.map(({ entry }) => entry)].slice(0, HERO_LIMIT);
    }
    return entries.map((entry) => {
      const media = entryMedia(entry);
      const artwork = media.backdrop_url || media.cover_url || "";
      return {
        ...entry,
        media,
        artwork,
        artworkKind: media.backdrop_url ? "backdrop" : (media.cover_url ? "poster" : "none"),
      };
    });
  }

  function formatRuntime(value) {
    if (value === null || value === undefined || value === "") return "";
    const text = String(value).trim();
    if (!text) return "";
    if (/^\d+(?:[.,]\d+)?$/.test(text)) return `${Math.round(Number(text.replace(",", ".")))} Min.`;
    return text;
  }

  function enhanceHomeCard(card, entry) {
    if (!card || card.classList.contains("is-ranked")) return card;
    const preview = card.querySelector(".home-card-preview");
    if (!preview || preview.dataset.homeExperienceV2 === "true") return card;
    preview.dataset.homeExperienceV2 = "true";

    const media = entryMedia(entry);
    preview.querySelector(".home-card-preview-actions")?.remove();
    preview.querySelector(":scope > strong")?.remove();
    preview.querySelector(".home-card-preview-meta")?.remove();

    const legacyGenres = preview.querySelector(".home-card-preview-genres");
    let tasteReason = "";
    if (legacyGenres) {
      const marker = " · Passt: ";
      const current = String(legacyGenres.textContent || "");
      const markerIndex = current.indexOf(marker);
      if (markerIndex >= 0) {
        tasteReason = current.slice(markerIndex + marker.length).trim();
        legacyGenres.textContent = current.slice(0, markerIndex).trim();
      } else {
        legacyGenres.textContent = (media.genres || []).slice(0, 3).join(" · ") || "";
      }
    }

    const detailMeta = document.createElement("span");
    detailMeta.className = "home-card-hover-meta";
    detailMeta.textContent = [
      media.year || (media.first_air_date ? String(media.first_air_date).slice(0, 4) : ""),
      media.rating ? `★ ${media.rating}` : "",
      formatRuntime(media.runtime),
      entry.kind === "movie" ? "Film" : entry.kind === "series" ? "Serie" : "Anime",
    ].filter(Boolean).join(" · ");

    const description = document.createElement("span");
    description.className = "home-card-preview-description";
    description.textContent = String(media.description || media.overview || "").trim();
    if (!description.textContent) description.hidden = true;

    const match = document.createElement("span");
    match.className = "home-card-preview-match";
    match.textContent = tasteReason ? `Passt zu dir: ${tasteReason}` : "";
    if (!match.textContent) match.hidden = true;

    const openHint = document.createElement("span");
    openHint.className = "home-card-preview-open";
    openHint.textContent = "Details öffnen  →";

    if (legacyGenres) legacyGenres.before(detailMeta);
    else preview.appendChild(detailMeta);
    preview.append(description, match, openHint);
    return card;
  }

  function install() {
    if (window.__royalHomeExperienceV2Installed) return true;
    if (
      !window.__royalTasteProfileV2Installed
      || typeof window.createHomeCard !== "function"
      || typeof window.homeHeroCandidates !== "function"
      || typeof window.homeAllEntries !== "function"
      || typeof window.loadDiscoveryProfile !== "function"
    ) return false;

    window.__royalHomeExperienceV2Installed = true;
    window.homeHeroCandidates = homeExperienceHeroCandidates;

    const originalCreateHomeCard = window.createHomeCard;
    window.createHomeCard = function homeExperienceCard(entry, ...args) {
      return enhanceHomeCard(originalCreateHomeCard(entry, ...args), entry);
    };

    // Repaint the current home view after replacing the hero/card seams. Hero
    // index is reset because the previous 4+3 legacy candidate list no longer
    // has the same semantic ordering.
    state.home.heroIndex = 0;
    if (state.tab === "home" && typeof renderHome === "function") renderHome();
    return true;
  }

  if (!install()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (install() || attempts >= 30) window.clearInterval(timer);
    }, 50);
  }
})();
