/* Royal Taste Profile v2: strict personal ranking, explainability and feedback. */
(() => {
  "use strict";

  if (window.__royalTasteProfileV2Installed) return;

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
  const sessionExposure = new Set();
  const scoreCache = new Map();

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
      if (token === "anime") return "anime";
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
    const list = Array.isArray(values) ? values : (values ? [values] : []);
    const result = [];
    const seen = new Set();
    for (const raw of list) {
      const source = raw && typeof raw === "object"
        ? (raw.name || raw.Name || raw.title || raw.Title || "")
        : raw;
      const value = canonicalValue(dimension, source);
      const key = value.toLocaleLowerCase();
      if (value && !seen.has(key)) {
        seen.add(key);
        result.push(value);
      }
      if (result.length >= 12) break;
    }
    return result;
  }

  function tasteV2Metadata(entry) {
    const media = homeEntryMedia(entry);
    const base = tasteMetadata(entry.kind, media);
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
    const result = new Map();
    Object.entries(profile?.dimensions?.[dimension] || {}).forEach(([name, score]) => {
      const numeric = Number(score);
      if (Number.isFinite(numeric)) result.set(String(name).toLocaleLowerCase(), { name, score: numeric });
    });
    return result;
  }

  function tasteV2LogicalKey(entry) {
    if (typeof discoveryV2LogicalKey === "function") return discoveryV2LogicalKey(entry);
    return homeEntryKey(entry);
  }

  function tasteV2FeedbackKey(entry) {
    return tasteV2LogicalKey(entry) || homeEntryKey(entry);
  }

  function tasteV2ScoreEntry(entry, profile = loadDiscoveryProfile()) {
    const cacheKey = `${tasteV2LogicalKey(entry)}|${Number(profile.updatedAt || profile.updated_at || 0)}|${Number(state.home.discoveryShuffle || 0)}`;
    if (scoreCache.has(cacheKey)) return scoreCache.get(cacheKey);
    const metadata = tasteV2Metadata(entry);
    const policy = profile.ranking || {};
    const negativeMultiplier = Number(policy.negative_multiplier ?? 1.55);
    const confidence = Math.max(0, Math.min(1, Number(profile.confidence || 0)));
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
        reasons.push({ dimension, value: hit.name, contribution, profileScore: hit.score });
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
    const key = tasteV2LogicalKey(entry);
    const sessionPenalty = sessionExposure.has(key) ? 18 : 0;
    const exposurePenalty = typeof discoveryV2ExposurePenalty === "function"
      ? discoveryV2ExposurePenalty(entry, "personal")
      : 0;
    const media = homeEntryMedia(entry);
    const ratingBonus = Number(media.rating || 0) * 0.10;
    const score = positive + negative - unknownPenalty - sessionPenalty - exposurePenalty + ratingBonus;
    const coverage = total ? known / total : 0;
    reasons.sort((left, right) => Math.abs(right.contribution) - Math.abs(left.contribution));
    const result = {
      score,
      positive,
      negative,
      coverage,
      unknownPenalty,
      reasons: reasons.slice(0, 8),
    };
    scoreCache.set(cacheKey, result);
    return result;
  }

  function strictPersonalEntries() {
    const profile = loadDiscoveryProfile();
    const recent = new Set((profile.recent || []).slice(0, 24).map((event) => event.key));
    const pool = homeAllEntries().filter((entry) => {
      const direct = homeEntryKey(entry);
      const logical = tasteV2LogicalKey(entry);
      return !recent.has(direct) && !recent.has(logical);
    });
    const scored = pool.map((entry) => ({ entry, ...tasteV2ScoreEntry(entry, profile) }))
      .sort((left, right) => right.score - left.score);

    if (Number(profile.interactions || 0) < 2 || Number(profile.confidence || 0) < 0.18) {
      return typeof discoveryV2SelectDiverse === "function"
        ? discoveryV2SelectDiverse(scored, 24)
        : scored.slice(0, 24).map(({ entry }) => entry);
    }

    const minAffinity = Number(profile.ranking?.personal_min_affinity ?? 1.25);
    const minCoverage = Number(profile.ranking?.personal_min_coverage ?? 0.18);
    const adjacentFloor = Number(profile.ranking?.adjacent_min_affinity ?? 0.10);
    const strong = scored.filter((candidate) =>
      candidate.score >= minAffinity
      && candidate.coverage >= minCoverage
      && candidate.positive > Math.abs(candidate.negative));
    const adjacent = scored.filter((candidate) =>
      !strong.includes(candidate)
      && candidate.score >= adjacentFloor
      && candidate.positive > 0
      && candidate.negative > -Math.max(2.5, candidate.positive));

    const selected = [];
    const selectedKeys = new Set();
    const addDiverse = (candidates, limit) => {
      const remaining = candidates.filter(({ entry }) => !selectedKeys.has(tasteV2LogicalKey(entry)));
      const entries = typeof discoveryV2SelectDiverse === "function"
        ? discoveryV2SelectDiverse(remaining, limit)
        : remaining.slice(0, limit).map(({ entry }) => entry);
      for (const entry of entries) {
        const key = tasteV2LogicalKey(entry);
        if (key && !selectedKeys.has(key)) {
          selectedKeys.add(key);
          selected.push(entry);
        }
      }
    };

    // The personal lane is intentionally no longer 4/2/1.  Its visible seven
    // cards are five strong matches plus at most two adjacent discoveries.
    addDiverse(strong, 5);
    addDiverse(adjacent, Math.max(0, 7 - selected.length));
    addDiverse(strong, Math.max(0, 24 - selected.length));
    addDiverse(adjacent, Math.max(0, 24 - selected.length));
    return selected.slice(0, 24);
  }

  function renderTasteSummaryV2(profile = loadDiscoveryProfile(), offline = false) {
    const target = document.getElementById("taste-profile-summary");
    if (!target) return;
    const favorites = Object.entries(profile.genres || {})
      .filter(([, score]) => Number(score) > 0.25)
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .slice(0, 5)
      .map(([name]) => name);
    const interactions = Number(profile.interactions || 0);
    if (!interactions) {
      target.textContent = "Noch neutral – Royal lernt erst durch deine Bedienung.";
      return;
    }
    const confidence = Number(profile.confidence || 0);
    const confidenceText = confidence >= .82
      ? "Profil sehr sicher"
      : confidence >= .62 ? "Profil sicher" : confidence >= .35 ? "Profil lernt noch" : "Profil im Aufbau";
    const breakdown = profile.signal_breakdown || {};
    target.textContent = [
      confidenceText,
      `${interactions} Lernsignale`,
      favorites.length ? `Stark: ${favorites.join(", ")}` : "",
      Number(breakdown.explicit || 0) ? `${breakdown.explicit} direkte Bewertungen` : "",
      offline ? "nur lokaler Stand" : "",
    ].filter(Boolean).join(" · ");
  }

  function explainCard(card, entry) {
    const result = tasteV2ScoreEntry(entry);
    const positives = result.reasons
      .filter((reason) => reason.contribution > 0)
      .slice(0, 3)
      .map((reason) => reason.value);
    const preview = card.querySelector(".home-card-preview-genres");
    if (preview && positives.length) {
      const original = preview.textContent;
      preview.textContent = `${original} · Passt: ${positives.join(", ")}`;
    }
    card.dataset.tasteScore = result.score.toFixed(2);
    card.dataset.tasteCoverage = result.coverage.toFixed(2);
  }

  function addQuickFeedback(card, entry) {
    if (!card || card.querySelector(".taste-v2-dismiss")) return;
    const art = card.querySelector(".home-card-art");
    if (!art) return;
    const control = document.createElement("button");
    control.type = "button";
    control.className = "taste-v2-dismiss";
    control.setAttribute("aria-label", "Nicht für mich");
    control.title = "Nicht für mich · Titel ausblenden und ähnliche Inhalte seltener zeigen";
    control.textContent = "⊘";
    const activate = async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (control.dataset.busy === "true") return;
      control.dataset.busy = "true";
      try {
        const media = homeEntryMedia(entry);
        const response = await api.tasteFeedback({
          item_key: tasteV2FeedbackKey(entry),
          action: "dismiss",
          source: "home",
          media_type: entry.kind,
          title: media.title || entry.item?.title || "",
          metadata: {
            ...tasteMetadata(entry.kind, media),
            franchise: media.franchise || media.collection || media.belongs_to_collection || "",
          },
        });
        if (response?.profile) applyServerTasteProfile(response.profile);
        scoreCache.clear();
        renderHome();
      } catch (error) {
        console.warn("Geschmacksfeedback konnte nicht gespeichert werden:", error);
        control.dataset.busy = "false";
      }
    };
    control.addEventListener("pointerdown", (event) => event.stopPropagation());
    control.addEventListener("click", activate);
    art.appendChild(control);
  }

  function installStyle() {
    if (document.getElementById("taste-v2-style")) return;
    const style = document.createElement("style");
    style.id = "taste-v2-style";
    style.textContent = `
      .home-card-art{position:relative}
      .taste-v2-dismiss{position:absolute;z-index:8;right:10px;top:10px;width:31px;height:31px;display:grid;place-items:center;border:1px solid rgba(255,255,255,.28);border-radius:999px;background:rgba(8,10,14,.76);color:#fff;font-size:18px;line-height:1;opacity:0;transform:translateY(-3px);transition:.18s ease;backdrop-filter:blur(8px);cursor:pointer}
      .home-card:hover .taste-v2-dismiss,.home-card:focus-within .taste-v2-dismiss,.taste-v2-dismiss:focus{opacity:1;transform:none;outline:none}
      .taste-v2-dismiss:hover,.taste-v2-dismiss:focus{border-color:#ff2438;background:rgba(130,8,20,.88)}
      .taste-v2-dismiss[data-busy="true"]{opacity:.45;pointer-events:none}
      @media(max-width:760px){.taste-v2-dismiss{opacity:.92;transform:none;right:8px;top:8px;width:29px;height:29px}}
    `;
    document.head.appendChild(style);
  }

  function recordVisiblePersonalForReshuffle() {
    strictPersonalEntries().slice(0, 7).forEach((entry) => {
      const key = tasteV2LogicalKey(entry);
      if (key) sessionExposure.add(key);
    });
    scoreCache.clear();
  }

  function install() {
    if (window.__royalTasteProfileV2Installed) return true;
    if (
      typeof window.homePersonalizedEntries !== "function"
      || typeof window.createHomeCard !== "function"
      || typeof window.renderHome !== "function"
      || typeof window.loadDiscoveryProfile !== "function"
    ) return false;

    window.__royalTasteProfileV2Installed = true;
    installStyle();

    window.homePersonalizedEntries = strictPersonalEntries;

    if (typeof window.allowedHomeEntries === "function") {
      const originalAllowed = window.allowedHomeEntries;
      window.allowedHomeEntries = function tasteV2Allowed(entries, profile = loadDiscoveryProfile()) {
        const base = originalAllowed(entries, profile);
        const blocked = new Set(profile.blocked_items || []);
        return base.filter((entry) =>
          !blocked.has(tasteV2LogicalKey(entry))
          && !blocked.has(homeEntryKey(entry)));
      };
    }

    window.renderTasteProfileSummary = renderTasteSummaryV2;

    const originalCreateHomeCard = window.createHomeCard;
    window.createHomeCard = function tasteV2HomeCard(entry, ...args) {
      const card = originalCreateHomeCard(entry, ...args);
      if (state.tab === "home") {
        explainCard(card, entry);
        addQuickFeedback(card, entry);
      }
      return card;
    };

    if (typeof window.shuffleHomeDiscovery === "function") {
      const originalShuffle = window.shuffleHomeDiscovery;
      window.shuffleHomeDiscovery = function tasteV2Shuffle(...args) {
        recordVisiblePersonalForReshuffle();
        return originalShuffle(...args);
      };
    }

    // app.js may already have captured the legacy shuffle function in an event
    // listener before this delayed policy layer loads.  Capture phase guarantees
    // that an explicit click still suppresses the cards the user just rejected.
    const shuffleButton = document.getElementById("home-discovery-shuffle");
    if (shuffleButton && shuffleButton.dataset.tasteV2Capture !== "true") {
      shuffleButton.dataset.tasteV2Capture = "true";
      shuffleButton.addEventListener("click", recordVisiblePersonalForReshuffle, { capture: true });
    }

    // Refresh the already rendered first paint after replacing Discovery v2.
    scoreCache.clear();
    renderTasteSummaryV2(loadDiscoveryProfile());
    if (state.tab === "home") renderHome();
    return true;
  }

  if (!install()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (install() || attempts >= 20) window.clearInterval(timer);
    }, 50);
  }
})();
