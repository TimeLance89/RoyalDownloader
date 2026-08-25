/* Royal Abendregie: progressive, erklärbare Film- und Serienkuratierung. */
const MOOD_MATCH_STEPS = [
  {
    key: "format", word: "FORMAT", title: "Was soll heute laufen?",
    copy: "Erst der Rahmen, dann die Feinheiten. Nach dieser Wahl kannst du schon direkt kuratieren.",
    options: [
      { value: "movie", icon: "01", title: "Ein Film", copy: "Ein Abend, eine Geschichte, ein Ende" },
      { value: "series", icon: "02", title: "Eine Serie", copy: "Eine Folge oder der Anfang von mehr" },
      { value: "any", icon: "∞", title: "Beides offen", copy: "Der stärkste Treffer entscheidet" },
    ],
  },
  {
    key: "mood", word: "WIRKUNG", title: "Was soll der Titel mit dir machen?",
    copy: "Keine Genreprüfung. Wähle die Wirkung, die nach dem Abspann bleiben soll.",
    options: [
      { value: "pulse", icon: "↗", title: "Mich fesseln", copy: "Druck, Tempo und keine Leerlaufminute" },
      { value: "shadow", icon: "◐", title: "Dunkel abtauchen", copy: "Unbehagen, Rätsel und Gänsehaut" },
      { value: "laugh", icon: ":)", title: "Mich aufheitern", copy: "Leicht, klug oder herrlich albern" },
      { value: "wonder", icon: "✦", title: "Mich staunen lassen", copy: "Große Welten und starke Bilder" },
      { value: "heart", icon: "♥", title: "Mich berühren", copy: "Nähe, Gefühl und Figuren, die bleiben" },
      { value: "comfort", icon: "≈", title: "Mich runterbringen", copy: "Warm, zugänglich und ohne schwere Kante" },
    ],
  },
  {
    key: "company", word: "RUNDE", title: "Für wen wird heute gespielt?",
    copy: "Die Runde verändert die Passung. Familienauswahl bleibt streng bei familientauglichen Genres.",
    options: [
      { value: "alone", icon: "1", title: "Nur für mich", copy: "Geschmack ohne Kompromisse" },
      { value: "couple", icon: "2", title: "Zu zweit", copy: "Gemeinsamer Sog statt kleinster Nenner" },
      { value: "friends", icon: "+", title: "Mit Freunden", copy: "Energie, Gesprächsstoff und starke Momente" },
      { value: "family", icon: "◆", title: "Familienrunde", copy: "Familie, Animation und Abenteuer ohne Horrortitel" },
    ],
  },
];

const MOOD_MATCH_PROFILES = {
  pulse: {
    title: "Heute bleibt keine Minute liegen.",
    direct: ["Action", "Thriller", "Krimi", "Abenteuer"],
    related: ["Science-Fiction", "Mystery", "Krieg", "Western"],
    excluded: ["Familie", "Musik"],
    weights: { Action: 16, Thriller: 14, Krimi: 9, Abenteuer: 7, "Science-Fiction": 5 },
  },
  shadow: {
    title: "Das Licht bleibt besser an.",
    direct: ["Horror", "Mystery", "Thriller", "Krimi"],
    related: ["Science-Fiction", "Drama"],
    excluded: ["Familie", "Kinder", "Komödie", "Musik", "Romanze"],
    weights: { Horror: 17, Mystery: 14, Thriller: 11, Krimi: 7, Drama: 3 },
  },
  laugh: {
    title: "Leicht, aber nicht beliebig.",
    direct: ["Komödie"], related: ["Animation", "Familie", "Romanze", "Musik"],
    excluded: ["Horror", "Krieg"],
    weights: { Komödie: 18, Animation: 7, Familie: 5, Romanze: 4, Musik: 3 },
  },
  wonder: {
    title: "Eine andere Welt steht bereit.",
    direct: ["Science-Fiction", "Fantasy", "Abenteuer"],
    related: ["Animation", "Mystery", "Familie", "Action"], excluded: [],
    weights: { "Science-Fiction": 16, Fantasy: 15, Abenteuer: 10, Animation: 5, Mystery: 4 },
  },
  heart: {
    title: "Etwas, das länger bleibt.",
    direct: ["Drama", "Romanze", "Musik"], related: ["Komödie", "Familie", "Geschichte"],
    excluded: ["Horror"],
    weights: { Drama: 15, Romanze: 12, Musik: 7, Komödie: 4, Geschichte: 3 },
  },
  comfort: {
    title: "Der Abend darf weich landen.",
    direct: ["Komödie", "Familie", "Animation", "Romanze"],
    related: ["Abenteuer", "Drama", "Musik"],
    excluded: ["Horror", "Thriller", "Krimi", "Krieg"],
    weights: { Komödie: 14, Familie: 12, Animation: 10, Romanze: 8, Abenteuer: 4 },
  },
};

const MOOD_MATCH_RULES = MOOD_MATCH_PROFILES;
const MOOD_DEFAULT_ANSWERS = { format: "any", mood: "open", company: "alone" };
const MOOD_REFINEMENT_GROUPS = [
  {
    key: "duration", title: "Zeitfenster", copy: "Unbekannte Laufzeiten zählen bei einem Limit nicht als Treffer.",
    options: [
      { value: "any", label: "Offen" }, { value: "90", label: "Bis 90 Min." },
      { value: "120", label: "Bis 2 Std." }, { value: "150", label: "Bis 2½ Std." },
    ],
  },
  {
    key: "tempo", title: "Tempo", copy: "Energie, nicht Härte.",
    options: [
      { value: "any", label: "Offen" }, { value: "quiet", label: "Ruhig" },
      { value: "balanced", label: "Im Fluss" }, { value: "drive", label: "Voller Zug" },
    ],
  },
  {
    key: "discovery", title: "Entdeckung", copy: "Sicherer Konsens oder Titel abseits der Masse.",
    options: [
      { value: "balanced", label: "Ausgewogen" }, { value: "safe", label: "Sicherer Treffer" },
      { value: "hidden", label: "Geheimtipp" }, { value: "surprise", label: "Überraschung" },
    ],
  },
  {
    key: "era", title: "Epoche", copy: "Das Erscheinungsjahr ist ein hartes Kriterium.",
    options: [
      { value: "any", label: "Alle Jahre" }, { value: "new", label: "Seit 2018" },
      { value: "modern", label: "2000–2017" }, { value: "classic", label: "Vor 2000" },
    ],
  },
  {
    key: "library", title: "Jellyfin", copy: "Nur eindeutige Bibliothekszustände werden berücksichtigt.",
    options: [
      { value: "any", label: "Alles" }, { value: "owned", label: "Sofort ansehen" },
      { value: "missing", label: "Neu entdecken" },
    ],
  },
  {
    key: "minRating", title: "Bewertung", copy: "Fehlende Bewertungen bestehen eine Mindestgrenze nicht.",
    options: [
      { value: "any", label: "Offen" }, { value: "7", label: "Ab 7,0" },
      { value: "8", label: "Ab 8,0" },
    ],
  },
];

const MOOD_AVOID_GENRES = [
  "Horror", "Thriller", "Action", "Krimi", "Drama", "Romanze", "Komödie", "Animation", "Dokumentation",
];
const MOOD_GENRE_ALIASES = {
  action: "Action", adventure: "Abenteuer", abenteuer: "Abenteuer", animation: "Animation",
  comedy: "Komödie", komödie: "Komödie", crime: "Krimi", krimi: "Krimi",
  documentary: "Dokumentation", dokumentarfilm: "Dokumentation", dokumentation: "Dokumentation",
  drama: "Drama", family: "Familie", familie: "Familie", kids: "Kinder", kinder: "Kinder",
  fantasy: "Fantasy", history: "Geschichte", geschichte: "Geschichte", horror: "Horror",
  music: "Musik", musik: "Musik", mystery: "Mystery", romance: "Romanze", romanze: "Romanze",
  "science fiction": "Science-Fiction", "science-fiction": "Science-Fiction", "sci-fi": "Science-Fiction",
  thriller: "Thriller", war: "Krieg", krieg: "Krieg", western: "Western",
};

let moodMatchReturnFocus = null;
let moodMatchGeneration = 0;

function createMoodRefinements() {
  return {
    duration: "any", tempo: "any", discovery: "balanced", era: "any",
    library: "any", minRating: "any", avoid: [],
  };
}

function createMoodState() {
  return {
    step: 0, answers: {}, inferred: [], refinements: createMoodRefinements(),
    draftRefinements: null, results: [], analysis: [], dismissed: [], open: true,
    view: "question", returnAfterDetail: false, requestId: 0,
  };
}

function canonicalMoodGenre(value) {
  const clean = String(value || "").trim();
  return MOOD_GENRE_ALIASES[clean.toLocaleLowerCase("de-DE")] || clean;
}

function normalizedMoodGenres(media) {
  const rawGenres = [media?.genres, media?.genre, media?.categories]
    .flatMap((value) => Array.isArray(value) ? value : (value ? String(value).split(/[,;/|]/) : []));
  return new Set(rawGenres
    .map((genre) => typeof genre === "object" ? (genre.name || genre.title || "") : genre)
    .map(canonicalMoodGenre).filter(Boolean));
}

function moodHasGenre(genres, name) {
  return genres.has(canonicalMoodGenre(name));
}

function moodHasAnyGenre(genres, names = []) {
  return names.some((name) => moodHasGenre(genres, name));
}

function moodRuntimeMinutes(media) {
  const raw = Array.isArray(media?.runtime) ? media.runtime[0] : media?.runtime;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  const value = String(raw || "").toLocaleLowerCase("de-DE");
  const hours = Number(value.match(/(\d+(?:[.,]\d+)?)\s*(?:h|std)/)?.[1]?.replace(",", ".") || 0);
  const minutes = Number(value.match(/(\d+)\s*(?:min|minute)/)?.[1] || 0);
  if (hours || minutes) return Math.round(hours * 60 + minutes);
  const standalone = Number(value.match(/^\s*(\d{2,3})\s*$/)?.[1] || 0);
  return standalone >= 20 && standalone <= 400 ? standalone : 0;
}

function moodMediaYear(media) {
  return Number(String(media?.year || media?.release_date || media?.first_air_date || "")
    .match(/\b(19|20)\d{2}\b/)?.[0] || 0);
}

function moodLibraryStatus(entry) {
  if (typeof mediaJellyfinStatus === "function") return mediaJellyfinStatus(homeEntryMedia(entry));
  const media = homeEntryMedia(entry);
  if (media.jellyfin_status) return media.jellyfin_status;
  if (media.in_jellyfin === true) return "owned";
  if (media.in_jellyfin === false) return "missing";
  return "unknown";
}

function moodEffectiveAnswers(answers = {}) {
  return { ...MOOD_DEFAULT_ANSWERS, ...answers };
}

function moodFamilyPool(entries) {
  return entries.filter((entry) => {
    const media = homeEntryMedia(entry);
    const genres = normalizedMoodGenres(media);
    if (!genres.size || media.adult === true) return false;
    if (moodHasAnyGenre(genres, ["Horror", "Thriller", "Krimi", "Krieg", "Erotik"])) return false;
    return moodHasAnyGenre(genres, ["Familie", "Kinder", "Animation", "Abenteuer", "Fantasy", "Komödie"]);
  });
}

function moodIntentTier(entry, answers) {
  const effective = moodEffectiveAnswers(answers);
  if (effective.mood === "open") return 0;
  const genres = normalizedMoodGenres(homeEntryMedia(entry));
  const rules = MOOD_MATCH_RULES[effective.mood];
  if (!rules || !genres.size || moodHasAnyGenre(genres, rules.excluded)) return 3;
  if (moodHasAnyGenre(genres, rules.direct)) return 0;
  if (moodHasAnyGenre(genres, rules.related)) return 1;
  return 2;
}

function moodMatchesIntent(entry, answers) {
  return moodIntentTier(entry, answers) < 2;
}

function moodMatchesRefinements(entry, refinements = createMoodRefinements()) {
  const media = homeEntryMedia(entry);
  const genres = normalizedMoodGenres(media);
  if ((refinements.avoid || []).some((genre) => moodHasGenre(genres, genre))) return false;
  if (refinements.duration !== "any") {
    const runtime = moodRuntimeMinutes(media);
    if (!runtime || runtime > Number(refinements.duration)) return false;
  }
  const year = moodMediaYear(media);
  if (refinements.era === "new" && (!year || year < 2018)) return false;
  if (refinements.era === "modern" && (!year || year < 2000 || year > 2017)) return false;
  if (refinements.era === "classic" && (!year || year >= 2000)) return false;
  if (refinements.library !== "any" && moodLibraryStatus(entry) !== refinements.library) return false;
  if (refinements.minRating !== "any" && Number(media.rating || 0) < Number(refinements.minRating)) return false;
  return true;
}

function moodCompanyScore(genres, company) {
  const weights = {
    alone: { Mystery: 3, Thriller: 2, Drama: 2, "Science-Fiction": 1 },
    couple: { Drama: 4, Romanze: 4, Komödie: 3, Mystery: 2, Thriller: 1 },
    friends: { Action: 5, Komödie: 5, Horror: 4, Abenteuer: 3, Thriller: 2 },
    family: { Familie: 12, Animation: 11, Abenteuer: 7, Fantasy: 5, Komödie: 4 },
  }[company] || {};
  return Object.entries(weights).reduce(
    (score, [genre, weight]) => score + (moodHasGenre(genres, genre) ? weight : 0), 0,
  );
}

function moodTempoScore(genres, tempo) {
  if (tempo === "drive") {
    return ["Action", "Thriller", "Horror", "Krimi", "Abenteuer"]
      .reduce((score, genre) => score + (moodHasGenre(genres, genre) ? 4 : 0), 0);
  }
  if (tempo === "quiet") {
    let score = ["Drama", "Romanze", "Dokumentation", "Geschichte"]
      .reduce((total, genre) => total + (moodHasGenre(genres, genre) ? 4 : 0), 0);
    if (moodHasAnyGenre(genres, ["Action", "Horror"])) score -= 5;
    return score;
  }
  if (tempo === "balanced") {
    return moodHasAnyGenre(genres, ["Abenteuer", "Komödie", "Mystery", "Drama"]) ? 3 : 0;
  }
  return 0;
}

function moodDiscoveryScore(media, discovery, key) {
  const rating = Number(media.rating || 0);
  const votes = Math.max(0, Number(media.vote_count || 0));
  const confidence = Math.log10(votes + 1);
  if (discovery === "safe") return rating * 1.1 + confidence * 3.2;
  if (discovery === "hidden") return rating * 1.3 - confidence * 1.6;
  if (discovery === "surprise") return stableDiscoveryHash(`mood-surprise|${key}`) / 4294967295 * 12;
  return rating * .75 + confidence * 1.15;
}

function moodMatchScore(entry, answers, profile = loadDiscoveryProfile(), refinements = createMoodRefinements()) {
  const effective = moodEffectiveAnswers(answers);
  const media = homeEntryMedia(entry);
  const genres = normalizedMoodGenres(media);
  const mood = MOOD_MATCH_PROFILES[effective.mood];
  let score = 0;
  if (mood) {
    Object.entries(mood.weights).forEach(([genre, weight]) => {
      if (moodHasGenre(genres, genre)) score += weight;
    });
  }
  score += moodCompanyScore(genres, effective.company);
  score += moodTempoScore(genres, refinements.tempo);
  score += moodDiscoveryScore(media, refinements.discovery, homeEntryKey(entry));
  Object.entries(profile?.genres || {}).forEach(([genre, weight]) => {
    if (moodHasGenre(genres, genre)) score += Math.max(-3, Math.min(3, Number(weight || 0) * .08));
  });
  if ((profile?.recent || []).slice(0, 30).some((event) => event.key === homeEntryKey(entry))) score -= 7;
  if (effective.format === "any") score += Math.max(-1.5, Math.min(1.5, Number(profile?.kinds?.[entry.kind] || 0) * .04));
  score += stableDiscoveryHash(`${localDateKey()}|abendregie|${JSON.stringify(effective)}|${homeEntryKey(entry)}`) / 4294967295;
  return score;
}

function moodPrimaryGenre(entry, answers) {
  const genres = normalizedMoodGenres(homeEntryMedia(entry));
  const profile = MOOD_MATCH_PROFILES[moodEffectiveAnswers(answers).mood];
  return [...(profile?.direct || []), ...(profile?.related || []), ...genres]
    .map(canonicalMoodGenre).find((genre) => genres.has(genre)) || "";
}

function moodBasePool(answers, refinements = createMoodRefinements()) {
  const effective = moodEffectiveAnswers(answers);
  let entries = allowedHomeEntries(homeAllEntries());
  const unique = typeof uniqueHomeContentEntries === "function" ? uniqueHomeContentEntries : uniqueHomeEntries;
  entries = unique(entries);
  if (effective.format === "movie") entries = entries.filter((entry) => entry.kind === "movie");
  if (effective.format === "series") entries = entries.filter((entry) => entry.kind === "series");
  if (effective.company === "family") entries = moodFamilyPool(entries);
  entries = entries.filter((entry) => moodMatchesRefinements(entry, refinements));
  if (effective.mood !== "open") entries = entries.filter((entry) => moodMatchesIntent(entry, effective));
  return entries;
}

function moodMatchAnalyses(answers, refinements = createMoodRefinements()) {
  const profile = loadDiscoveryProfile();
  const ranked = moodBasePool(answers, refinements).map((entry) => ({
    entry, tier: moodIntentTier(entry, answers),
    score: moodMatchScore(entry, answers, profile, refinements),
  })).sort((left, right) => left.tier - right.tier || right.score - left.score);
  const selected = [];
  const genreCounts = new Map();
  const kindCounts = new Map();
  const remaining = ranked.slice();
  while (remaining.length && selected.length < 12) {
    remaining.sort((left, right) => {
      const leftGenre = moodPrimaryGenre(left.entry, answers);
      const rightGenre = moodPrimaryGenre(right.entry, answers);
      const leftAdjusted = left.score - (genreCounts.get(leftGenre) || 0) * 3.2 - (kindCounts.get(left.entry.kind) || 0) * .8;
      const rightAdjusted = right.score - (genreCounts.get(rightGenre) || 0) * 3.2 - (kindCounts.get(right.entry.kind) || 0) * .8;
      return left.tier - right.tier || rightAdjusted - leftAdjusted;
    });
    const next = remaining.shift();
    selected.push(next);
    const genre = moodPrimaryGenre(next.entry, answers);
    genreCounts.set(genre, (genreCounts.get(genre) || 0) + 1);
    kindCounts.set(next.entry.kind, (kindCounts.get(next.entry.kind) || 0) + 1);
  }
  return selected;
}

function moodMatchResults(answers, refinements = createMoodRefinements()) {
  return moodMatchAnalyses(answers, refinements).map(({ entry }) => entry);
}

async function prepareMoodCandidates() {
  const entries = homeAllEntries();
  await Promise.allSettled([
    hydrateHomeMovieArtwork(
      entries.filter((entry) => entry.kind === "movie").slice(0, 100).map((entry) => entry.item),
      { render: false },
    ),
    hydrateHomeSeriesArtwork(
      entries.filter((entry) => entry.kind === "series").slice(0, 100).map((entry) => entry.item),
      { render: false },
    ),
  ]);
}

function moodAnswerLabel(stepKey, value) {
  if (stepKey === "mood" && value === "open") return "Wirkung offen";
  return MOOD_MATCH_STEPS.find((step) => step.key === stepKey)
    ?.options.find((option) => option.value === value)?.title || value;
}

function moodRefinementLabel(key, value) {
  return MOOD_REFINEMENT_GROUPS.find((group) => group.key === key)
    ?.options.find((option) => option.value === value)?.label || value;
}

function moodSetText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function focusMoodHeading(id = "mood-title") {
  requestAnimationFrame(() => {
    const heading = document.getElementById(id);
    if (!heading) return;
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  });
}

function renderMoodJourney() {
  const moodState = state.home.mood;
  const journey = document.getElementById("mood-journey");
  journey.replaceChildren();
  MOOD_MATCH_STEPS.forEach((step, index) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${index + 1} ${step.word}`;
    const isResults = moodState.view === "results" || moodState.view === "refine";
    const isCurrent = !isResults && moodState.step === index;
    const canOpen = isResults || index <= moodState.step || Boolean(moodState.answers[step.key]);
    button.classList.toggle("is-current", isCurrent);
    button.classList.toggle("is-complete", isResults || index < moodState.step);
    button.disabled = !canOpen;
    if (isCurrent) button.setAttribute("aria-current", "step");
    if (canOpen) button.addEventListener("click", () => jumpMoodStep(index));
    item.appendChild(button);
    journey.appendChild(item);
  });
}

function moodArtworkCandidates(entry, portrait = false) {
  const media = homeEntryMedia(entry);
  const raw = portrait ? [media.cover_url, media.backdrop_url] : [media.backdrop_url, media.cover_url];
  return raw.flatMap((url) => (
    typeof api !== "undefined" && typeof api.coverCandidates === "function" ? api.coverCandidates(url) : [url]
  )).filter((url, index, urls) => url && urls.indexOf(url) === index);
}

function appendMoodArtwork(parent, entry, portrait = false) {
  const candidates = moodArtworkCandidates(entry, portrait);
  if (!candidates.length) return;
  const image = document.createElement("img");
  let index = 0;
  image.src = candidates[index];
  image.alt = "";
  image.loading = "eager";
  image.decoding = "async";
  image.addEventListener("error", () => {
    index += 1;
    if (index < candidates.length) image.src = candidates[index];
    else image.remove();
  });
  parent.appendChild(image);
}

function renderMoodLive() {
  const moodState = state.home.mood;
  const effective = moodEffectiveAnswers(moodState.answers);
  const refinements = moodState.view === "refine" && moodState.draftRefinements
    ? moodState.draftRefinements : moodState.refinements;
  const analyses = moodMatchAnalyses(effective, refinements);
  const count = moodBasePool(effective, refinements).length;
  moodSetText("mood-live-count", count === 1 ? "1 Titel im Licht" : `${count} Titel im Licht`);
  moodSetText("mood-live-status", count
    ? "Alle sichtbaren Titel erfüllen die gesetzten Muss-Kriterien."
    : "Kein Titel erfüllt gerade alle Muss-Kriterien. Es wird nichts heimlich gelockert.");

  const recipe = document.getElementById("mood-recipe");
  recipe.replaceChildren();
  MOOD_MATCH_STEPS.forEach((step, index) => {
    const answer = moodState.answers[step.key];
    if (!answer) {
      const placeholder = document.createElement("span");
      placeholder.textContent = `${step.word} offen`;
      recipe.appendChild(placeholder);
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = moodAnswerLabel(step.key, answer);
    button.addEventListener("click", () => jumpMoodStep(index));
    recipe.appendChild(button);
  });

  const preview = document.getElementById("mood-preview-stack");
  preview.replaceChildren();
  analyses.slice(0, 3).forEach(({ entry }) => {
    const frame = document.createElement("span");
    frame.className = "mood-preview-frame";
    appendMoodArtwork(frame, entry, true);
    preview.appendChild(frame);
  });
}

function renderMoodOption(step, option, index) {
  const moodState = state.home.mood;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "mood-option";
  button.dataset.value = option.value;
  button.setAttribute("aria-pressed", String(moodState.answers[step.key] === option.value));
  const icon = document.createElement("span");
  icon.className = "mood-option-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = option.icon || String(index + 1).padStart(2, "0");
  const copy = document.createElement("span");
  copy.className = "mood-option-copy";
  const title = document.createElement("strong");
  title.textContent = option.title;
  const detail = document.createElement("small");
  detail.textContent = option.copy;
  copy.append(title, detail);
  button.append(icon, copy);
  button.addEventListener("click", () => {
    const changed = moodState.answers[step.key] !== option.value;
    moodState.answers[step.key] = option.value;
    moodState.inferred = moodState.inferred.filter((key) => key !== step.key);
    if (changed) {
      MOOD_MATCH_STEPS.slice(moodState.step + 1).forEach((later) => {
        delete moodState.answers[later.key];
        moodState.inferred = moodState.inferred.filter((key) => key !== later.key);
      });
      moodState.dismissed = [];
    }
    renderMoodMatch();
    document.querySelector(`#mood-options [data-value="${CSS.escape(option.value)}"]`)?.focus();
  });
  return button;
}

function renderMoodQuestion() {
  const moodState = state.home.mood;
  const step = MOOD_MATCH_STEPS[moodState.step];
  const modal = document.getElementById("mood-modal");
  modal.dataset.view = "question";
  modal.dataset.step = step.key;
  modal.dataset.stepIndex = String(moodState.step);
  modal.dataset.tone = moodState.answers.company === "family" ? "family" : (moodState.answers.mood || "neutral");
  modal.style.setProperty("--mood-focus", String(Math.max(.08, .24 - moodState.step * .055)));
  document.getElementById("mood-question").hidden = false;
  document.getElementById("mood-results").hidden = true;
  document.getElementById("mood-refine").hidden = true;
  moodSetText("mood-step-label", `${step.word} · ${moodState.step + 1} VON ${MOOD_MATCH_STEPS.length}`);
  moodSetText("mood-title", step.title);
  moodSetText("mood-copy", step.copy);
  moodSetText("mood-stage-number", String(moodState.step + 1).padStart(2, "0"));
  moodSetText("mood-stage-word", step.word);
  document.getElementById("mood-progress-bar").style.width = `${((moodState.step + 1) / MOOD_MATCH_STEPS.length) * 100}%`;
  const options = document.getElementById("mood-options");
  options.replaceChildren(...step.options.map((option, index) => renderMoodOption(step, option, index)));
  const selected = Boolean(moodState.answers[step.key]);
  const back = document.getElementById("mood-back");
  back.hidden = moodState.step === 0;
  back.textContent = "Zurück";
  const quick = document.getElementById("mood-quick");
  quick.hidden = !moodState.answers.format || moodState.step === MOOD_MATCH_STEPS.length - 1;
  quick.textContent = "Treffer jetzt zeigen";
  document.getElementById("mood-refine-toggle").hidden = true;
  const next = document.getElementById("mood-next");
  next.disabled = !selected;
  next.innerHTML = moodState.step === MOOD_MATCH_STEPS.length - 1
    ? "Treffer kuratieren <span aria-hidden=\"true\">✦</span>"
    : "Weiter schärfen <span aria-hidden=\"true\">→</span>";
}

function moodMatchGrade(analysis, answers) {
  if (moodEffectiveAnswers(answers).mood === "open") return "BESTE PASSUNG";
  return analysis.tier === 0 ? "SEHR NAHER TREFFER" : "STARKER VERWANDTER TREFFER";
}

function moodReasons(analysis, answers, refinements) {
  const effective = moodEffectiveAnswers(answers);
  const media = homeEntryMedia(analysis.entry);
  const genres = normalizedMoodGenres(media);
  const reasons = [];
  if (effective.mood !== "open") {
    const profile = MOOD_MATCH_PROFILES[effective.mood];
    const matched = [...profile.direct, ...profile.related].find((genre) => moodHasGenre(genres, genre));
    if (matched) reasons.push(`${moodAnswerLabel("mood", effective.mood)} · ${matched}`);
  } else {
    reasons.push("Wirkung bewusst offen");
  }
  reasons.push(moodAnswerLabel("company", effective.company));
  if (refinements.tempo !== "any") reasons.push(`Tempo · ${moodRefinementLabel("tempo", refinements.tempo)}`);
  if (refinements.duration !== "any") reasons.push(`${moodRuntimeMinutes(media)} Min. im Zeitfenster`);
  if (Number(media.rating || 0) >= 7.5) reasons.push(`Stark bewertet · ${Number(media.rating).toFixed(1)}`);
  if (refinements.library === "owned") reasons.push("Sofort in Jellyfin");
  if (refinements.library === "missing") reasons.push("Noch nicht in Jellyfin");
  return reasons.slice(0, 4);
}

function moodMediaMeta(entry) {
  const media = homeEntryMedia(entry);
  const status = moodLibraryStatus(entry);
  const statusLabel = {
    owned: "IN JELLYFIN", missing: "NOCH NICHT IN JELLYFIN", checking: "JELLYFIN WIRD GEPRÜFT",
    unconfigured: "JELLYFIN NICHT VERBUNDEN", unavailable: "JELLYFIN NICHT ERREICHBAR",
  }[status] || "JELLYFIN-STATUS OFFEN";
  return [
    entry.kind === "movie" ? "FILM" : "SERIE",
    media.year || String(media.release_date || media.first_air_date || "").slice(0, 4),
    media.runtime || "", media.rating ? `★ ${media.rating}` : "", statusLabel,
  ].filter(Boolean).join(" · ");
}

function openMoodEntry(entry, trigger) {
  suspendMoodMatchForDetail(trigger);
  const key = entry.kind === "movie" ? entry.item.slug : entry.item.base_slug;
  openHomeEntry(entry.kind, key);
}

function renderMoodLead(analysis) {
  const moodState = state.home.mood;
  const entry = analysis.entry;
  const media = homeEntryMedia(entry);
  const card = document.createElement("article");
  card.className = "mood-lead-card";
  const art = document.createElement("span");
  art.className = "mood-lead-art";
  appendMoodArtwork(art, entry);
  const shade = document.createElement("span");
  shade.className = "mood-lead-shade";
  const copy = document.createElement("div");
  copy.className = "mood-lead-copy";
  const grade = document.createElement("span");
  grade.className = "mood-match-grade";
  grade.textContent = moodMatchGrade(analysis, moodState.answers);
  const title = document.createElement("h3");
  title.translate = false;
  title.textContent = media.title || "Unbekannter Titel";
  const meta = document.createElement("span");
  meta.className = "mood-lead-meta";
  meta.textContent = moodMediaMeta(entry);
  const description = document.createElement("p");
  description.className = "mood-lead-description";
  description.textContent = media.description || media.overview || "Die Metadaten liefern noch keine Inhaltsbeschreibung.";
  const reasons = document.createElement("div");
  reasons.className = "mood-lead-reasons";
  moodReasons(analysis, moodState.answers, moodState.refinements).forEach((reason) => {
    const chip = document.createElement("span");
    chip.textContent = reason;
    reasons.appendChild(chip);
  });
  const actions = document.createElement("div");
  actions.className = "mood-lead-actions";
  const open = document.createElement("button");
  open.type = "button";
  open.className = "mood-lead-open";
  open.textContent = "Details öffnen";
  open.addEventListener("click", () => openMoodEntry(entry, open));
  const skip = document.createElement("button");
  skip.type = "button";
  skip.className = "mood-lead-skip";
  skip.textContent = "Nicht heute · nächsten zeigen";
  skip.addEventListener("click", moodAdvanceLead);
  actions.append(open, skip);
  copy.append(grade, title, meta, description, reasons, actions);
  card.append(art, shade, copy);
  return card;
}

function renderMoodResultCard(analysis) {
  const entry = analysis.entry;
  const media = homeEntryMedia(entry);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "mood-result-card";
  button.setAttribute("aria-label", `${media.title || "Titel"}, ${moodMatchGrade(analysis, state.home.mood.answers)}, Details öffnen`);
  const art = document.createElement("span");
  art.className = "mood-result-card-art";
  appendMoodArtwork(art, entry);
  const grade = document.createElement("span");
  grade.className = "mood-result-card-grade";
  grade.textContent = moodMatchGrade(analysis, state.home.mood.answers);
  art.appendChild(grade);
  const copy = document.createElement("span");
  copy.className = "mood-result-card-copy";
  const title = document.createElement("strong");
  title.translate = false;
  title.textContent = media.title || "Unbekannter Titel";
  const meta = document.createElement("small");
  meta.textContent = moodMediaMeta(entry);
  copy.append(title, meta);
  button.append(art, copy);
  button.addEventListener("click", () => openMoodEntry(entry, button));
  return button;
}

function moodRelaxationSuggestion(answers, refinements) {
  const candidates = [
    ["duration", "any", "Zeitfenster öffnen"],
    ["library", "any", "Jellyfin-Filter öffnen"],
    ["minRating", "any", "Bewertung öffnen"],
    ["era", "any", "Alle Jahre zulassen"],
  ];
  for (const [key, value, label] of candidates) {
    if (refinements[key] === value) continue;
    const relaxed = { ...refinements, avoid: [...(refinements.avoid || [])], [key]: value };
    const count = moodBasePool(answers, relaxed).length;
    if (count) return { key, value, label: `${label} · ${count} Treffer` };
  }
  if ((refinements.avoid || []).length) {
    const relaxed = { ...refinements, avoid: [] };
    const count = moodBasePool(answers, relaxed).length;
    if (count) return { key: "avoid", value: [], label: `No-Gos öffnen · ${count} Treffer` };
  }
  if (answers.mood !== "open") {
    const relaxedAnswers = { ...answers, mood: "open" };
    const count = moodBasePool(relaxedAnswers, refinements).length;
    if (count) {
      return {
        target: "answer", key: "mood", value: "open",
        label: `Wirkung offen lassen · ${count} Treffer`,
      };
    }
  }
  return null;
}

function renderMoodEmpty() {
  const moodState = state.home.mood;
  const empty = document.getElementById("mood-empty");
  empty.hidden = false;
  empty.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = "Kein sauberer Treffer.";
  const copy = document.createElement("p");
  copy.textContent = "Diese Kombination wird nicht mit unpassenden oder unbekannten Titeln aufgefüllt.";
  const suggestion = moodRelaxationSuggestion(moodEffectiveAnswers(moodState.answers), moodState.refinements);
  const action = document.createElement("button");
  action.type = "button";
  action.textContent = suggestion?.label || "Wirkung ändern";
  action.addEventListener("click", () => {
    if (suggestion) {
      if (suggestion.target === "answer") {
        moodState.answers[suggestion.key] = suggestion.value;
        if (!moodState.inferred.includes(suggestion.key)) moodState.inferred.push(suggestion.key);
      } else {
        moodState.refinements[suggestion.key] = suggestion.value;
      }
      renderMoodMatchResults();
    } else {
      jumpMoodStep(1);
    }
  });
  empty.append(title, copy, action);
}

function renderMoodResultSummary() {
  const moodState = state.home.mood;
  const summary = document.getElementById("mood-result-summary");
  summary.replaceChildren();
  MOOD_MATCH_STEPS.forEach((step, index) => {
    const value = moodEffectiveAnswers(moodState.answers)[step.key];
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = moodAnswerLabel(step.key, value);
    if (moodState.inferred.includes(step.key)) button.textContent += " · Standard";
    button.addEventListener("click", () => jumpMoodStep(index));
    summary.appendChild(button);
  });
}

function renderMoodMatchResults({ focus = false } = {}) {
  const moodState = state.home.mood;
  const modal = document.getElementById("mood-modal");
  moodState.view = "results";
  modal.dataset.view = "results";
  modal.dataset.tone = moodState.answers.company === "family" ? "family" : (moodState.answers.mood || "neutral");
  modal.style.setProperty("--mood-focus", ".06");
  document.getElementById("mood-question").hidden = true;
  document.getElementById("mood-refine").hidden = true;
  document.getElementById("mood-results").hidden = false;
  document.getElementById("mood-progress-bar").style.width = "100%";
  moodSetText("mood-stage-number", "★");
  moodSetText("mood-stage-word", "TREFFER");
  const all = moodMatchAnalyses(moodEffectiveAnswers(moodState.answers), moodState.refinements);
  moodState.analysis = all.filter(({ entry }) => !moodState.dismissed.includes(homeEntryKey(entry)));
  if (!moodState.analysis.length && all.length) {
    moodState.dismissed = [];
    moodState.analysis = all;
  }
  moodState.results = moodState.analysis.map(({ entry }) => entry);
  const lead = document.getElementById("mood-lead");
  const grid = document.getElementById("mood-result-grid");
  const empty = document.getElementById("mood-empty");
  lead.replaceChildren();
  grid.replaceChildren();
  empty.hidden = true;
  const profile = MOOD_MATCH_PROFILES[moodEffectiveAnswers(moodState.answers).mood];
  moodSetText("mood-results-title", moodState.analysis.length
    ? (profile?.title || "Ein Titel bleibt im Licht.") : "Kein Titel erfüllt alles.");
  renderMoodResultSummary();
  if (moodState.analysis.length) {
    lead.appendChild(renderMoodLead(moodState.analysis[0]));
    moodState.analysis.slice(1, 3).forEach((analysis) => grid.appendChild(renderMoodResultCard(analysis)));
    moodSetText("mood-alternatives-copy", moodState.analysis.length > 1
      ? "Zwei andere starke Schnitte desselben Abends" : "Kein weiterer Titel erfüllt alles sauber");
  } else {
    renderMoodEmpty();
  }
  const back = document.getElementById("mood-back");
  back.hidden = false;
  back.textContent = "Auswahl ändern";
  document.getElementById("mood-quick").hidden = true;
  document.getElementById("mood-refine-toggle").hidden = false;
  const next = document.getElementById("mood-next");
  next.disabled = false;
  next.innerHTML = "Neuer Abend <span aria-hidden=\"true\">↻</span>";
  renderMoodJourney();
  renderMoodLive();
  if (focus) focusMoodHeading("mood-results-title");
}

function renderMoodRefinement() {
  const moodState = state.home.mood;
  const options = document.getElementById("mood-refine-options");
  options.replaceChildren();
  MOOD_REFINEMENT_GROUPS.forEach((group) => {
    const section = document.createElement("section");
    section.className = "mood-refine-group";
    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = group.title;
    const copy = document.createElement("small");
    copy.textContent = group.copy;
    header.append(title, copy);
    const choices = document.createElement("div");
    choices.className = "mood-refine-choices";
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-label", group.title);
    group.options.forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "mood-refine-choice";
      button.textContent = option.label;
      button.setAttribute("aria-pressed", String(moodState.draftRefinements[group.key] === option.value));
      button.addEventListener("click", () => {
        moodState.draftRefinements[group.key] = option.value;
        renderMoodRefinement();
        renderMoodLive();
      });
      choices.appendChild(button);
    });
    section.append(header, choices);
    options.appendChild(section);
  });
  const avoidSection = document.createElement("section");
  avoidSection.className = "mood-refine-group";
  const avoidHeader = document.createElement("header");
  const avoidTitle = document.createElement("strong");
  avoidTitle.textContent = "No-Gos";
  const avoidCopy = document.createElement("small");
  avoidCopy.textContent = "Ein Ausschluss bleibt hart. Kein Titel darf ihn umgehen.";
  avoidHeader.append(avoidTitle, avoidCopy);
  const avoidChoices = document.createElement("div");
  avoidChoices.className = "mood-refine-choices";
  avoidChoices.setAttribute("role", "group");
  avoidChoices.setAttribute("aria-label", "Genres ausschließen");
  MOOD_AVOID_GENRES.forEach((genre) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mood-refine-choice";
    button.textContent = genre;
    button.setAttribute("aria-pressed", String(moodState.draftRefinements.avoid.includes(genre)));
    button.addEventListener("click", () => {
      const values = new Set(moodState.draftRefinements.avoid);
      if (values.has(genre)) values.delete(genre); else values.add(genre);
      moodState.draftRefinements.avoid = [...values];
      renderMoodRefinement();
      renderMoodLive();
    });
    avoidChoices.appendChild(button);
  });
  avoidSection.append(avoidHeader, avoidChoices);
  options.appendChild(avoidSection);
  const count = moodBasePool(moodEffectiveAnswers(moodState.answers), moodState.draftRefinements).length;
  moodSetText("mood-refine-count", count === 1 ? "1 sauberer Treffer" : `${count} saubere Treffer`);
}

function openMoodRefinement() {
  const moodState = state.home.mood;
  moodState.view = "refine";
  moodState.draftRefinements = {
    ...moodState.refinements,
    avoid: [...(moodState.refinements.avoid || [])],
  };
  const modal = document.getElementById("mood-modal");
  modal.dataset.view = "refine";
  document.getElementById("mood-question").hidden = true;
  document.getElementById("mood-results").hidden = true;
  document.getElementById("mood-refine").hidden = false;
  renderMoodRefinement();
  renderMoodJourney();
  renderMoodLive();
  focusMoodHeading("mood-refine-title");
}

function closeMoodRefinement(apply = false) {
  const moodState = state.home.mood;
  if (apply && moodState.draftRefinements) {
    moodState.refinements = {
      ...moodState.draftRefinements,
      avoid: [...(moodState.draftRefinements.avoid || [])],
    };
    moodState.dismissed = [];
  }
  moodState.draftRefinements = null;
  renderMoodMatchResults({ focus: true });
}

function resetMoodRefinement() {
  state.home.mood.draftRefinements = createMoodRefinements();
  renderMoodRefinement();
  renderMoodLive();
}

function renderMoodMatch() {
  const moodState = state.home.mood;
  if (moodState.view === "refine") {
    renderMoodRefinement();
    return;
  }
  if (moodState.step >= MOOD_MATCH_STEPS.length || moodState.view === "results") {
    renderMoodMatchResults();
    return;
  }
  moodState.view = "question";
  renderMoodQuestion();
  renderMoodJourney();
  renderMoodLive();
}

function setMoodBackgroundInert(enabled) {
  const modal = document.getElementById("mood-modal");
  [...modal.parentElement.children].forEach((sibling) => {
    if (sibling === modal) return;
    if (enabled) {
      if (!sibling.inert) sibling.dataset.moodInert = "true";
      sibling.inert = true;
    } else if (sibling.dataset.moodInert === "true") {
      sibling.inert = false;
      delete sibling.dataset.moodInert;
    }
  });
}

function openMoodMatch(trigger = null) {
  moodMatchReturnFocus = trigger || document.activeElement;
  const previous = state.home.mood;
  if (!previous?.answers || (!Object.keys(previous.answers).length && previous.view !== "results")) {
    state.home.mood = createMoodState();
  } else {
    state.home.mood.open = true;
  }
  const modal = document.getElementById("mood-modal");
  modal.classList.remove("hidden");
  document.body.classList.add("mood-open");
  setMoodBackgroundInert(true);
  stopHomeHeroRotation();
  renderMoodMatch();
  focusMoodHeading(state.home.mood.view === "results" ? "mood-results-title" : "mood-title");
  const generation = ++moodMatchGeneration;
  void prepareMoodCandidates().then(() => {
    if (generation !== moodMatchGeneration || !state.home.mood.open) return;
    renderMoodMatch();
  });
}

function closeMoodMatch(restoreFocus = true, preserveDetailReturn = false) {
  const modal = document.getElementById("mood-modal");
  if (modal.classList.contains("hidden")) return;
  modal.classList.add("hidden");
  document.body.classList.remove("mood-open");
  setMoodBackgroundInert(false);
  state.home.mood.open = false;
  state.home.mood.requestId += 1;
  moodMatchGeneration += 1;
  if (!preserveDetailReturn) state.home.mood.returnAfterDetail = false;
  if (state.tab === "home") scheduleHomeHeroRotation();
  if (restoreFocus && moodMatchReturnFocus?.isConnected) moodMatchReturnFocus.focus();
}

function suspendMoodMatchForDetail() {
  state.home.mood.returnAfterDetail = true;
  closeMoodMatch(false, true);
}

function resumeMoodMatchAfterDetail() {
  const moodState = state.home.mood;
  if (!moodState?.returnAfterDetail) return false;
  moodState.returnAfterDetail = false;
  moodState.open = true;
  moodState.view = "results";
  const modal = document.getElementById("mood-modal");
  modal.classList.remove("hidden");
  document.body.classList.add("mood-open");
  setMoodBackgroundInert(true);
  stopHomeHeroRotation();
  renderMoodMatchResults();
  requestAnimationFrame(() => document.querySelector("#mood-lead .mood-lead-open")?.focus());
  return true;
}

function jumpMoodStep(index) {
  const moodState = state.home.mood;
  moodState.view = "question";
  moodState.step = Math.max(0, Math.min(MOOD_MATCH_STEPS.length - 1, Number(index) || 0));
  moodState.draftRefinements = null;
  renderMoodMatch();
  focusMoodHeading();
}

async function showMoodResults({ quick = false } = {}) {
  const moodState = state.home.mood;
  if (!moodState.answers.format) return;
  if (quick) {
    MOOD_MATCH_STEPS.forEach((step) => {
      if (!moodState.answers[step.key]) {
        moodState.answers[step.key] = MOOD_DEFAULT_ANSWERS[step.key];
        moodState.inferred.push(step.key);
      }
    });
  }
  const requestId = ++moodState.requestId;
  const next = document.getElementById("mood-next");
  const quickButton = document.getElementById("mood-quick");
  next.disabled = true;
  quickButton.disabled = true;
  next.textContent = "Der Schnitt wird geschärft …";
  moodSetText("mood-live-status", "Metadaten werden ergänzt. Harte Kriterien bleiben unangetastet.");
  const timeout = new Promise((resolve) => window.setTimeout(resolve, 8000));
  await Promise.race([prepareMoodCandidates(), timeout]);
  if (!moodState.open || requestId !== moodState.requestId) return;
  moodState.step = MOOD_MATCH_STEPS.length;
  moodState.view = "results";
  moodState.dismissed = [];
  quickButton.disabled = false;
  renderMoodMatchResults({ focus: true });
}

async function moodMatchNext() {
  const moodState = state.home.mood;
  if (moodState.view === "results") {
    state.home.mood = createMoodState();
    renderMoodMatch();
    focusMoodHeading();
    return;
  }
  if (moodState.view === "refine") {
    closeMoodRefinement(true);
    return;
  }
  const step = MOOD_MATCH_STEPS[moodState.step];
  if (!moodState.answers[step.key]) return;
  if (moodState.step === MOOD_MATCH_STEPS.length - 1) {
    await showMoodResults();
    return;
  }
  moodState.step += 1;
  renderMoodMatch();
  focusMoodHeading();
}

function moodMatchQuickResult() {
  void showMoodResults({ quick: true });
}

function moodMatchBack() {
  const moodState = state.home.mood;
  if (moodState.view === "refine") {
    closeMoodRefinement(false);
    return;
  }
  if (moodState.view === "results") {
    jumpMoodStep(MOOD_MATCH_STEPS.length - 1);
    return;
  }
  jumpMoodStep(moodState.step - 1);
}

function moodAdvanceLead() {
  const lead = state.home.mood.analysis[0];
  if (!lead) return;
  state.home.mood.dismissed.push(homeEntryKey(lead.entry));
  renderMoodMatchResults();
  requestAnimationFrame(() => document.querySelector("#mood-lead .mood-lead-open")?.focus());
}

function handleMoodMatchKeydown(event) {
  if (!state.home.mood.open) return false;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    if (state.home.mood.view === "refine") closeMoodRefinement(false);
    else closeMoodMatch();
    return true;
  }
  if (event.key !== "Tab") return false;
  const focusable = [...document.querySelectorAll(
    "#mood-modal button:not([disabled]):not([hidden]), #mood-modal [href], #mood-modal [tabindex]:not([tabindex='-1'])",
  )].filter((element) => element.offsetParent !== null);
  if (!focusable.length) return false;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
  return false;
}
