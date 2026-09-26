import {
  MOOD_MATCH_STEPS, MOOD_MATCH_PROFILES, MOOD_REFINEMENT_GROUPS, MOOD_AVOID_GENRES,
  MOOD_GENRE_COMPASS
} from "./config.js";

export function createMoodView(root, { getState, getScope, model, actions, homeEntryMedia, homeEntryKey, coverCandidates }) {
  const document = root.ownerDocument;
  const CSS = document.defaultView.CSS;
  const find = id => id === root.id ? root : root.querySelector(`#${id}`);
  const bindings = new WeakMap();
  const bind = (element, event, callback) => {
    let events = bindings.get(element);
    if (!events) { events = new Map(); bindings.set(element, events); }
    events.set(event, callback);
  };
  function mount(scope) {
    for (const type of ["click", "error"]) scope.listen(root, type, event => {
      for (let node = event.target; node && node !== root; node = node.parentElement) {
        const callback = bindings.get(node)?.get(type);
        if (callback) { callback(event); return; }
      }
    }, type === "error");
  }
  const {
    moodEffectiveAnswers, moodFocusedGenres, moodBasePool, moodMatchAnalyses,
    moodAnswerLabel, moodMatchGrade, moodReasons, moodMediaMeta,
    moodRelaxationSuggestion
  } = model;
  const {
    selectMoodGenre, openMoodEntry, jumpMoodStep, moodAdvanceLead
  } = actions;
function renderMoodJourney() {
  const moodState = getState();
  const journey = find("mood-journey");
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
    if (canOpen) bind(button, "click", () => jumpMoodStep(index));
    item.appendChild(button);
    journey.appendChild(item);
  });
}

function renderMoodGenreCompass() {
  const moodState = getState();
  const compass = find("mood-genre-compass");
  const isMoodStep = moodState.view === "question" && MOOD_MATCH_STEPS[moodState.step]?.key === "mood";
  compass.hidden = !isMoodStep;
  if (!isMoodStep) return;

  const selected = moodFocusedGenres(moodState.answers);
  moodState.answers.genres = [...selected];
  if (selected.length) moodState.genreOpen = true;
  const toggle = find("mood-genre-toggle");
  const panel = find("mood-genre-panel");
  toggle.setAttribute("aria-expanded", String(Boolean(moodState.genreOpen)));
  toggle.querySelector("i").textContent = moodState.genreOpen ? "−" : "＋";
  panel.hidden = !moodState.genreOpen;
  moodSetText("mood-genre-toggle-meta", selected.length
    ? selected.join(" + ") : (moodState.genreOpen ? "Bis zu zwei auswählen" : "Alle 24 Genres öffnen"));
  if (!moodState.genreOpen) return;

  const options = find("mood-genre-options");
  options.replaceChildren(...MOOD_GENRE_COMPASS.map(({ name, code }) => {
    const active = selected.includes(name);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mood-genre-choice";
    button.dataset.value = name;
    button.setAttribute("aria-pressed", String(active));
    button.disabled = selected.length >= 2 && !active;
    const marker = document.createElement("small");
    marker.textContent = code;
    marker.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = name;
    button.append(marker, label);
    bind(button, "click", () => selectMoodGenre(name));
    return button;
  }));
  const count = moodBasePool(moodEffectiveAnswers(moodState.answers), moodState.refinements).length;
  const selectionCopy = selected.length
    ? `${selected.join(" + ")} · ${count} ${count === 1 ? "Treffer trägt" : "Treffer tragen"} ${selected.length === 2 ? "beide Genres" : "diesen Fokus"}`
    : "Kein Genre festgelegt. Die Wirkung führt den Schnitt.";
  moodSetText("mood-genre-status", selectionCopy);
  find("mood-genre-clear").disabled = !selected.length;
}

function renderMoodLive() {
  const moodState = getState();
  const effective = moodEffectiveAnswers(moodState.answers);
  const refinements = moodState.view === "refine" && moodState.draftRefinements
    ? moodState.draftRefinements : moodState.refinements;
  const analyses = moodMatchAnalyses(effective, refinements);
  const count = moodBasePool(effective, refinements).length;
  moodSetText("mood-live-count", count === 1 ? "1 Titel im Licht" : `${count} Titel im Licht`);
  moodSetText("mood-live-status", count
    ? "Alle sichtbaren Titel erfüllen die gesetzten Muss-Kriterien."
    : "Kein Titel erfüllt gerade alle Muss-Kriterien. Es wird nichts heimlich gelockert.");

  const recipe = find("mood-recipe");
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
    bind(button, "click", () => jumpMoodStep(index));
    recipe.appendChild(button);
  });
  if (effective.genres.length) {
    const genreButton = document.createElement("button");
    genreButton.type = "button";
    genreButton.textContent = effective.genres.join(" + ");
    bind(genreButton, "click", () => jumpMoodStep(1));
    recipe.appendChild(genreButton);
  }

  const preview = find("mood-preview-stack");
  preview.replaceChildren();
  analyses.slice(0, 3).forEach(({ entry }) => {
    const frame = document.createElement("span");
    frame.className = "mood-preview-frame";
    appendMoodArtwork(frame, entry, true);
    preview.appendChild(frame);
  });
}

function renderMoodOption(step, option, index) {
  const moodState = getState();
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
  bind(button, "click", () => {
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
    root.querySelector(`#mood-options [data-value="${CSS.escape(option.value)}"]`)?.focus();
  });
  return button;
}

function renderMoodQuestion() {
  const moodState = getState();
  const step = MOOD_MATCH_STEPS[moodState.step];
  const modal = find("mood-modal");
  modal.dataset.view = "question";
  modal.dataset.step = step.key;
  modal.dataset.stepIndex = String(moodState.step);
  modal.dataset.tone = moodState.answers.company === "family" ? "family" : (moodState.answers.mood || "neutral");
  modal.style.setProperty("--mood-focus", String(Math.max(.08, .24 - moodState.step * .055)));
  find("mood-question").hidden = false;
  find("mood-results").hidden = true;
  find("mood-refine").hidden = true;
  moodSetText("mood-step-label", `${step.word} · ${moodState.step + 1} VON ${MOOD_MATCH_STEPS.length}`);
  moodSetText("mood-title", step.title);
  moodSetText("mood-copy", step.copy);
  moodSetText("mood-stage-number", String(moodState.step + 1).padStart(2, "0"));
  moodSetText("mood-stage-word", step.word);
  find("mood-progress-bar").style.width = `${((moodState.step + 1) / MOOD_MATCH_STEPS.length) * 100}%`;
  const options = find("mood-options");
  options.replaceChildren(...step.options.map((option, index) => renderMoodOption(step, option, index)));
  renderMoodGenreCompass();
  const selected = Boolean(moodState.answers[step.key]);
  const back = find("mood-back");
  back.hidden = moodState.step === 0;
  back.textContent = "Zurück";
  const quick = find("mood-quick");
  quick.hidden = !moodState.answers.format || moodState.step === MOOD_MATCH_STEPS.length - 1;
  quick.textContent = "Treffer jetzt zeigen";
  find("mood-refine-toggle").hidden = true;
  const next = find("mood-next");
  next.disabled = !selected;
  next.innerHTML = moodState.step === MOOD_MATCH_STEPS.length - 1
    ? "Treffer kuratieren <span aria-hidden=\"true\">✦</span>"
    : "Weiter schärfen <span aria-hidden=\"true\">→</span>";
}

function renderMoodLead(analysis) {
  const moodState = getState();
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
  bind(open, "click", () => openMoodEntry(entry, open));
  const skip = document.createElement("button");
  skip.type = "button";
  skip.className = "mood-lead-skip";
  skip.textContent = "Nicht heute · nächsten zeigen";
  bind(skip, "click", moodAdvanceLead);
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
  button.setAttribute("aria-label", `${media.title || "Titel"}, ${moodMatchGrade(analysis, getState().answers)}, Details öffnen`);
  const art = document.createElement("span");
  art.className = "mood-result-card-art";
  appendMoodArtwork(art, entry);
  const grade = document.createElement("span");
  grade.className = "mood-result-card-grade";
  grade.textContent = moodMatchGrade(analysis, getState().answers);
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
  bind(button, "click", () => openMoodEntry(entry, button));
  return button;
}

function renderMoodEmpty() {
  const moodState = getState();
  const empty = find("mood-empty");
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
  bind(action, "click", () => {
    if (suggestion) {
      if (suggestion.target === "answer") {
        moodState.answers[suggestion.key] = suggestion.value;
        if (MOOD_MATCH_STEPS.some((step) => step.key === suggestion.key)
            && !moodState.inferred.includes(suggestion.key)) moodState.inferred.push(suggestion.key);
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
  const moodState = getState();
  const summary = find("mood-result-summary");
  summary.replaceChildren();
  MOOD_MATCH_STEPS.forEach((step, index) => {
    const value = moodEffectiveAnswers(moodState.answers)[step.key];
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = moodAnswerLabel(step.key, value);
    if (moodState.inferred.includes(step.key)) button.textContent += " · Standard";
    bind(button, "click", () => jumpMoodStep(index));
    summary.appendChild(button);
  });
  const genres = moodFocusedGenres(moodState.answers);
  if (genres.length) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `Genre · ${genres.join(" + ")}`;
    bind(button, "click", () => jumpMoodStep(1));
    summary.appendChild(button);
  }
}

function renderMoodMatchResults({ focus = false } = {}) {
  const moodState = getState();
  const modal = find("mood-modal");
  moodState.view = "results";
  modal.dataset.view = "results";
  modal.dataset.tone = moodState.answers.company === "family" ? "family" : (moodState.answers.mood || "neutral");
  modal.style.setProperty("--mood-focus", ".06");
  find("mood-question").hidden = true;
  find("mood-refine").hidden = true;
  find("mood-results").hidden = false;
  find("mood-progress-bar").style.width = "100%";
  moodSetText("mood-stage-number", "★");
  moodSetText("mood-stage-word", "TREFFER");
  const all = moodMatchAnalyses(moodEffectiveAnswers(moodState.answers), moodState.refinements);
  moodState.analysis = all.filter(({ entry }) => !moodState.dismissed.includes(homeEntryKey(entry)));
  if (!moodState.analysis.length && all.length) {
    moodState.dismissed = [];
    moodState.analysis = all;
  }
  moodState.results = moodState.analysis.map(({ entry }) => entry);
  const lead = find("mood-lead");
  const grid = find("mood-result-grid");
  const empty = find("mood-empty");
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
  const back = find("mood-back");
  back.hidden = false;
  back.textContent = "Auswahl ändern";
  find("mood-quick").hidden = true;
  find("mood-refine-toggle").hidden = false;
  const next = find("mood-next");
  next.disabled = false;
  next.innerHTML = "Neuer Abend <span aria-hidden=\"true\">↻</span>";
  renderMoodJourney();
  renderMoodLive();
  if (focus) focusMoodHeading("mood-results-title");
}

function renderMoodRefinement() {
  const moodState = getState();
  const options = find("mood-refine-options");
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
      bind(button, "click", () => {
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
    bind(button, "click", () => {
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

function renderMoodMatch() {
  const moodState = getState();
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

function moodSetText(id, value) {
  const element = find(id);
  if (element) element.textContent = value;
}

function focusMoodHeading(id = "mood-title") {
  getScope()?.frame(() => {
    const heading = find(id);
    if (!heading) return;
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  });
}

function moodArtworkCandidates(entry, portrait = false) {
  const media = homeEntryMedia(entry);
  const raw = portrait ? [media.cover_url, media.backdrop_url] : [media.backdrop_url, media.cover_url];
  return raw.flatMap((url) => (
    coverCandidates(url)
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
  bind(image, "error", () => {
    index += 1;
    if (index < candidates.length) image.src = candidates[index];
    else image.remove();
  });
  parent.appendChild(image);
}

return { mount, renderMoodJourney, renderMoodGenreCompass, renderMoodLive, renderMoodOption, renderMoodQuestion, renderMoodLead, renderMoodResultCard, renderMoodEmpty, renderMoodResultSummary, renderMoodMatchResults, renderMoodRefinement, renderMoodMatch, moodSetText, focusMoodHeading, moodArtworkCandidates, appendMoodArtwork };
}
