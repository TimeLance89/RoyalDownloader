/* Abendmodus: momentbezogene Empfehlungen und schwache Geschmackssignale. */
const MOOD_MATCH_STEPS = [
  {
    key: "mood",
    label: "1 von 4",
    number: "01",
    word: "GEFÜHL",
    title: "Wie soll sich der Abend anfühlen?",
    copy: "Nicht was du sonst schaust – was du jetzt brauchst.",
    options: [
      { value: "horror", icon: "◒", title: "Dunkel & brutal", copy: "Horror, Angst und keine Schonung" },
      { value: "adrenaline", icon: "↯", title: "Volle Spannung", copy: "Tempo, Gefahr und Nervenkitzel" },
      { value: "laugh", icon: "◡", title: "Einfach lachen", copy: "Leicht, schräg oder herrlich albern" },
      { value: "wonder", icon: "✦", title: "Andere Welten", copy: "Staunen, Abenteuer und große Bilder" },
      { value: "comfort", icon: "☼", title: "Wohlfühlen", copy: "Warm, emotional und nicht zu schwer" },
    ],
  },
  {
    key: "company",
    label: "2 von 4",
    number: "02",
    word: "RUNDE",
    title: "Wer schaut heute mit?",
    copy: "Die gleiche Stimmung funktioniert nicht in jeder Runde.",
    options: [
      { value: "alone", icon: "●", title: "Nur ich", copy: "Volle Freiheit bei der Auswahl" },
      { value: "couple", icon: "●●", title: "Zu zweit", copy: "Etwas, das euch beide packt" },
      { value: "friends", icon: "▲", title: "Mit Freunden", copy: "Gesprächsstoff und starke Momente" },
      { value: "family", icon: "◆", title: "Mit der Familie", copy: "Sicherer, zugänglicher, gern animiert" },
    ],
  },
  {
    key: "intensity",
    label: "3 von 4",
    number: "03",
    word: "DOSIS",
    title: "Wie viel darf es heute sein?",
    copy: "Von entspanntem Nebenbei bis zur vollen Breitseite.",
    options: [
      { value: "easy", icon: "Ⅰ", title: "Ganz entspannt", copy: "Leicht zugänglich und ruhig" },
      { value: "balanced", icon: "Ⅱ", title: "Genau richtig", copy: "Spannend, aber nicht erschöpfend" },
      { value: "hard", icon: "Ⅲ", title: "Ohne Kompromisse", copy: "Intensiv, düster oder maximal" },
    ],
  },
  {
    key: "format",
    label: "4 von 4",
    number: "04",
    word: "FORMAT",
    title: "Worauf lässt du dich ein?",
    copy: "Ein abgeschlossener Filmabend oder der Anfang von mehr.",
    options: [
      { value: "movie", icon: "▶", title: "Ein Film", copy: "Heute noch Anfang und Ende" },
      { value: "series", icon: "▤", title: "Eine Serie", copy: "Eine Folge – vielleicht auch mehr" },
      { value: "any", icon: "∞", title: "Überrasch mich", copy: "Nur der Treffer zählt" },
    ],
  },
];

const MOOD_MATCH_PROFILES = {
  horror: {
    tone: "horror",
    title: "Dunkel. Hart. Ohne Schonprogramm.",
    genres: { Horror: 15, Thriller: 7, Mystery: 4, Krimi: 2 },
  },
  adrenaline: {
    tone: "adrenaline",
    title: "Keine ruhige Minute.",
    genres: { Action: 13, Thriller: 9, Abenteuer: 5, Krimi: 3 },
  },
  laugh: {
    tone: "laugh",
    title: "Heute darf es leicht sein.",
    genres: { Komödie: 15, Animation: 5, Familie: 4, Romanze: 2 },
  },
  wonder: {
    tone: "wonder",
    title: "Raus aus dieser Welt.",
    genres: { "Science-Fiction": 13, Fantasy: 12, Abenteuer: 8, Animation: 3 },
  },
  comfort: {
    tone: "comfort",
    title: "Ein Abend, der gut tut.",
    genres: { Drama: 7, Komödie: 9, Romanze: 8, Familie: 5, Musik: 3 },
  },
};

let moodMatchReturnFocus = null;

function normalizedMoodGenres(media) {
  return new Set((media.genres || [])
    .map((genre) => String(genre || "").trim().toLocaleLowerCase("de-DE"))
    .filter(Boolean));
}

function moodHasGenre(genres, name) {
  const expected = String(name).toLocaleLowerCase("de-DE");
  return [...genres].some((genre) => genre === expected
    || genre.includes(expected) || expected.includes(genre));
}

function moodFamilyPool(entries) {
  const strict = entries.filter((entry) => {
    const genres = normalizedMoodGenres(homeEntryMedia(entry));
    if (moodHasGenre(genres, "Horror") || moodHasGenre(genres, "Erotik")) return false;
    return ["Animation", "Familie", "Kinder"].some((genre) => moodHasGenre(genres, genre));
  });
  if (strict.length >= 6) return strict;
  return entries.filter((entry) => {
    const genres = normalizedMoodGenres(homeEntryMedia(entry));
    if (["Horror", "Erotik", "Thriller"].some((genre) => moodHasGenre(genres, genre))) return false;
    return ["Animation", "Familie", "Kinder", "Abenteuer", "Komödie", "Fantasy"]
      .some((genre) => moodHasGenre(genres, genre));
  });
}

function moodMatchScore(entry, answers, profile) {
  const media = homeEntryMedia(entry);
  const genres = normalizedMoodGenres(media);
  const mood = MOOD_MATCH_PROFILES[answers.mood] || MOOD_MATCH_PROFILES.wonder;
  let score = Number(media.rating || 0) * .6;
  Object.entries(mood.genres).forEach(([genre, weight]) => {
    if (moodHasGenre(genres, genre)) score += weight;
  });

  const companyWeights = {
    alone: { Mystery: 3, Thriller: 2, Drama: 2 },
    couple: { Drama: 3, Romanze: 4, Komödie: 2, Thriller: 1 },
    friends: { Action: 4, Komödie: 4, Horror: 3, Abenteuer: 2 },
    family: { Animation: 12, Familie: 12, Abenteuer: 5, Komödie: 4, Fantasy: 3 },
  }[answers.company] || {};
  Object.entries(companyWeights).forEach(([genre, weight]) => {
    if (moodHasGenre(genres, genre)) score += weight;
  });

  if (answers.intensity === "hard") {
    if (moodHasGenre(genres, "Horror")) score += 7;
    if (moodHasGenre(genres, "Thriller") || moodHasGenre(genres, "Action")) score += 4;
    if (moodHasGenre(genres, "Familie")) score -= 4;
  } else if (answers.intensity === "easy") {
    if (["Komödie", "Familie", "Animation", "Romanze"].some((genre) => moodHasGenre(genres, genre))) score += 5;
    if (moodHasGenre(genres, "Horror")) score -= 7;
  }

  if (answers.format === "movie") score += entry.kind === "movie" ? 8 : -12;
  if (answers.format === "series") score += entry.kind === "series" ? 8 : -12;
  Object.entries(profile.genres || {}).forEach(([genre, weight]) => {
    if (moodHasGenre(genres, genre)) score += Number(weight || 0) * .08;
  });
  if ((profile.recent || []).slice(0, 18).some((event) => event.key === homeEntryKey(entry))) score -= 5;
  score += stableDiscoveryHash(`${localDateKey()}|mood|${JSON.stringify(answers)}|${homeEntryKey(entry)}`) / 4294967295;
  return score;
}

function moodMatchResults(answers) {
  let pool = allowedHomeEntries(homeAllEntries());
  if (answers.company === "family") pool = moodFamilyPool(pool);
  if (answers.format === "movie") pool = pool.filter((entry) => entry.kind === "movie");
  if (answers.format === "series") pool = pool.filter((entry) => entry.kind === "series");
  const profile = loadDiscoveryProfile();
  return uniqueHomeEntries(pool)
    .map((entry) => ({ entry, score: moodMatchScore(entry, answers, profile) }))
    .sort((left, right) => right.score - left.score)
    .slice(0, 12)
    .map(({ entry }) => entry);
}

function moodAnswerLabel(stepKey, value) {
  return MOOD_MATCH_STEPS.find((step) => step.key === stepKey)
    ?.options.find((option) => option.value === value)?.title || value;
}

function recordMoodTasteSignal(answers) {
  const mood = MOOD_MATCH_PROFILES[answers.mood];
  if (!mood) return;
  const signalKey = JSON.stringify(answers);
  if (state.home.mood.recordedKey === signalKey) return;
  state.home.mood.recordedKey = signalKey;
  const profile = loadDiscoveryProfile();
  Object.keys(mood.genres).slice(0, 4).forEach((genre) => {
    profile.genres[genre] = Number(profile.genres[genre] || 0) + .2;
  });
  if (answers.format === "movie" || answers.format === "series") {
    profile.kinds[answers.format] = Number(profile.kinds[answers.format] || 0) + .1;
  }
  profile.interactions = Number(profile.interactions || 0) + 1;
  profile.updatedAt = Date.now();
  saveDiscoveryProfile(profile);
  api.tasteEvent({
    action: "search",
    source: "mood-session",
    media_type: answers.format === "any" ? "" : answers.format,
    query: `Abendmodus: ${answers.mood}`,
    metadata: {
      genres: Object.keys(mood.genres).slice(0, 4),
      tags: [answers.company, answers.intensity],
    },
  }).then((response) => {
    if (response?.profile) applyServerTasteProfile(response.profile);
  }).catch((error) => console.warn("Abendmodus-Signal konnte nicht gespeichert werden:", error));
}

function renderMoodMatchResults() {
  const moodState = state.home.mood;
  const answers = moodState.answers;
  const profile = MOOD_MATCH_PROFILES[answers.mood] || MOOD_MATCH_PROFILES.wonder;
  moodState.results = moodMatchResults(answers);
  document.getElementById("mood-modal").dataset.tone = answers.company === "family" ? "family" : profile.tone;
  document.getElementById("mood-progress-bar").style.width = "100%";
  document.getElementById("mood-stage-number").textContent = "★";
  document.getElementById("mood-stage-word").textContent = "TREFFER";
  document.getElementById("mood-step-label").textContent = "DEIN PROGRAMM FÜR JETZT";
  document.getElementById("mood-title").textContent = answers.company === "family"
    ? "Großes Kino für die ganze Runde."
    : profile.title;
  document.getElementById("mood-copy").textContent = moodState.results.length
    ? "Nach Stimmung, Runde und Intensität aus deinem aktuellen Royal-Katalog gewählt."
    : "Für diese Kombination fehlen gerade passende Titel im geladenen Katalog.";
  document.getElementById("mood-options").replaceChildren();
  const results = document.getElementById("mood-results");
  results.hidden = false;
  const summary = document.getElementById("mood-result-summary");
  summary.replaceChildren();
  ["mood", "company", "intensity", "format"].forEach((key) => {
    const chip = document.createElement("span");
    chip.textContent = moodAnswerLabel(key, answers[key]);
    summary.appendChild(chip);
  });
  const grid = document.getElementById("mood-result-grid");
  grid.replaceChildren();
  moodState.results.forEach((entry, index) => {
    const card = createHomeCard(entry, 0, index < 4, index === 0 ? "mood-lead" : "mood-result");
    card.addEventListener("click", () => closeMoodMatch(false), { capture: true });
    grid.appendChild(card);
  });
  const back = document.getElementById("mood-back");
  back.hidden = false;
  back.textContent = "Antworten ändern";
  const next = document.getElementById("mood-next");
  next.disabled = false;
  next.innerHTML = "Neu starten <span aria-hidden=\"true\">↻</span>";
  recordMoodTasteSignal(answers);
}

function renderMoodMatch() {
  const moodState = state.home.mood;
  if (moodState.step >= MOOD_MATCH_STEPS.length) {
    renderMoodMatchResults();
    return;
  }
  const step = MOOD_MATCH_STEPS[moodState.step];
  const selected = moodState.answers[step.key] || "";
  const tone = moodState.answers.mood || "neutral";
  document.getElementById("mood-modal").dataset.tone = moodState.answers.company === "family" ? "family" : tone;
  document.getElementById("mood-progress-bar").style.width = `${((moodState.step + 1) / MOOD_MATCH_STEPS.length) * 100}%`;
  document.getElementById("mood-stage-number").textContent = step.number;
  document.getElementById("mood-stage-word").textContent = step.word;
  document.getElementById("mood-step-label").textContent = step.label;
  document.getElementById("mood-title").textContent = step.title;
  document.getElementById("mood-copy").textContent = step.copy;
  document.getElementById("mood-results").hidden = true;
  const options = document.getElementById("mood-options");
  options.replaceChildren();
  step.options.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mood-option";
    button.dataset.value = option.value;
    button.setAttribute("aria-pressed", String(selected === option.value));
    button.innerHTML = `<span class="mood-option-icon" aria-hidden="true">${option.icon}</span><span><strong>${option.title}</strong><small>${option.copy}</small></span>`;
    button.addEventListener("click", () => {
      moodState.answers[step.key] = option.value;
      renderMoodMatch();
      document.getElementById("mood-next").focus();
    });
    options.appendChild(button);
  });
  const back = document.getElementById("mood-back");
  back.hidden = moodState.step === 0;
  back.textContent = "Zurück";
  const next = document.getElementById("mood-next");
  next.disabled = !selected;
  next.innerHTML = moodState.step === MOOD_MATCH_STEPS.length - 1
    ? "Treffer finden <span aria-hidden=\"true\">✦</span>"
    : "Weiter <span aria-hidden=\"true\">→</span>";
}

function openMoodMatch(trigger = null) {
  moodMatchReturnFocus = trigger || document.activeElement;
  state.home.mood = { step: 0, answers: {}, results: [], open: true, recordedKey: "" };
  const modal = document.getElementById("mood-modal");
  modal.classList.remove("hidden");
  document.body.classList.add("mood-open");
  stopHomeHeroRotation();
  renderMoodMatch();
  requestAnimationFrame(() => document.querySelector("#mood-options .mood-option")?.focus());
}

function closeMoodMatch(restoreFocus = true) {
  const modal = document.getElementById("mood-modal");
  if (modal.classList.contains("hidden")) return;
  modal.classList.add("hidden");
  document.body.classList.remove("mood-open");
  state.home.mood.open = false;
  if (state.tab === "home") scheduleHomeHeroRotation();
  if (restoreFocus) moodMatchReturnFocus?.focus();
}

function moodMatchNext() {
  const moodState = state.home.mood;
  if (moodState.step >= MOOD_MATCH_STEPS.length) {
    moodState.step = 0;
    moodState.answers = {};
    moodState.results = [];
    renderMoodMatch();
    return;
  }
  const step = MOOD_MATCH_STEPS[moodState.step];
  if (!moodState.answers[step.key]) return;
  moodState.step += 1;
  renderMoodMatch();
}

function moodMatchBack() {
  const moodState = state.home.mood;
  moodState.step = Math.max(0, Math.min(MOOD_MATCH_STEPS.length - 1, moodState.step - 1));
  renderMoodMatch();
}

function handleMoodMatchKeydown(event) {
  if (!state.home.mood.open) return false;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeMoodMatch();
    return true;
  }
  if (event.key !== "Tab") return false;
  const focusable = [...document.querySelectorAll("#mood-modal button:not([disabled]):not([hidden])")]
    .filter((element) => element.offsetParent !== null);
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
