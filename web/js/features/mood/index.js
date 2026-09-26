import { createScope, delay } from "../../core/lifecycle.js";
import { createDialog } from "../../shared/components/dialog.js";
import { createMoodModel } from "./model.js";
import { createMoodView } from "./view.js";
import {
  MOOD_MATCH_STEPS, MOOD_DEFAULT_ANSWERS
} from "./config.js";

export function createMood(root, {
  model: modelInputs, homeEntryMedia, homeEntryKey, homeAllEntries, coverCandidates,
  hydrateHomeMovieArtwork, hydrateHomeSeriesArtwork, openHomeEntry,
  stopHomeHeroRotation, scheduleHomeHeroRotation, isHome,
}) {
  const document = root.ownerDocument;
  const CSS = document.defaultView.CSS;
  const find = id => id === root.id ? root : root.querySelector(`#${id}`);
  let owner = null, viewScope = null;
  let moodMatchReturnFocus = null, moodMatchGeneration = 0;
  const model = createMoodModel(modelInputs);
  const {
    createMoodState, createMoodRefinements, moodFocusedGenres
  } = model;
  let localState = { ...createMoodState(), open: false };
  const dialog = createDialog(root, { dismissible: false, initialFocus: () => find(localState.view === "results" ? "mood-results-title" : "mood-title") });
  const view = createMoodView(root, { getState: () => localState, getScope: () => viewScope,
    model, homeEntryMedia, homeEntryKey, coverCandidates,
    actions: { selectMoodGenre, openMoodEntry, jumpMoodStep, moodAdvanceLead },
  });
  const {
    renderMoodJourney, renderMoodGenreCompass, renderMoodLive, renderMoodMatchResults,
    renderMoodRefinement, renderMoodMatch, moodSetText, focusMoodHeading
  } = view;
async function prepareMoodCandidates(signal = viewScope?.signal) {
  if (!viewScope?.active || signal?.aborted) return;
  const entries = homeAllEntries();
  await Promise.allSettled([
    hydrateHomeMovieArtwork(
      entries.filter((entry) => entry.kind === "movie").slice(0, 100).map((entry) => entry.item),
      { render: false, signal },
    ),
    hydrateHomeSeriesArtwork(
      entries.filter((entry) => entry.kind === "series").slice(0, 100).map((entry) => entry.item),
      { render: false, signal },
    ),
  ]);
}

function toggleMoodGenreCompass() {
  localState.genreOpen = !localState.genreOpen;
  renderMoodGenreCompass();
  if (localState.genreOpen) {
    viewScope?.frame(() => root.querySelector("#mood-genre-options button:not([disabled])")?.focus());
  }
}

function selectMoodGenre(genre) {
  const moodState = localState;
  const selected = new Set(moodFocusedGenres(moodState.answers));
  if (selected.has(genre)) selected.delete(genre);
  else if (selected.size < 2) selected.add(genre);
  moodState.answers.genres = [...selected];
  if (selected.size && !moodState.answers.mood) {
    moodState.answers.mood = "open";
    if (!moodState.inferred.includes("mood")) moodState.inferred.push("mood");
  }
  if (!selected.size && moodState.answers.mood === "open" && moodState.inferred.includes("mood")) {
    delete moodState.answers.mood;
    moodState.inferred = moodState.inferred.filter((key) => key !== "mood");
  }
  moodState.dismissed = [];
  renderMoodGenreCompass();
  renderMoodLive();
  find("mood-next").disabled = !moodState.answers.mood;
  viewScope?.frame(() => root.querySelector(
    `#mood-genre-options button[data-value="${CSS.escape(genre)}"]`,
  )?.focus());
}

function clearMoodGenreFocus() {
  localState.answers.genres = [];
  if (localState.answers.mood === "open" && localState.inferred.includes("mood")) {
    delete localState.answers.mood;
    localState.inferred = localState.inferred.filter((key) => key !== "mood");
  }
  localState.dismissed = [];
  renderMoodGenreCompass();
  renderMoodLive();
  find("mood-next").disabled = !localState.answers.mood;
  viewScope?.frame(() => find("mood-genre-toggle")?.focus());
}

function openMoodEntry(entry, trigger) {
  suspendMoodMatchForDetail(trigger);
  const key = entry.kind === "movie" ? entry.item.slug : entry.item.base_slug;
  openHomeEntry(entry.kind, key);
}

function openMoodRefinement() {
  const moodState = localState;
  moodState.view = "refine";
  moodState.draftRefinements = {
    ...moodState.refinements,
    avoid: [...(moodState.refinements.avoid || [])],
  };
  const modal = find("mood-modal");
  modal.dataset.view = "refine";
  find("mood-question").hidden = true;
  find("mood-results").hidden = true;
  find("mood-refine").hidden = false;
  renderMoodRefinement();
  renderMoodJourney();
  renderMoodLive();
  focusMoodHeading("mood-refine-title");
}

function closeMoodRefinement(apply = false) {
  const moodState = localState;
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
  localState.draftRefinements = createMoodRefinements();
  renderMoodRefinement();
  renderMoodLive();
}

function setMoodBackgroundInert(enabled) {
  const modal = find("mood-modal");
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
  if (!owner?.active || viewScope?.active) return;
  viewScope = dialog.open(trigger || document.activeElement);
  view.mount(viewScope);
  moodMatchReturnFocus = trigger || document.activeElement;
  const previous = localState;
  if (!previous?.answers || (!Object.keys(previous.answers).length && previous.view !== "results")) {
    localState = createMoodState();
  } else {
    localState.open = true;
  }
  const modal = find("mood-modal");
  modal.classList.remove("hidden");
  document.body.classList.add("mood-open");
  setMoodBackgroundInert(true);
  stopHomeHeroRotation();
  renderMoodMatch();
  focusMoodHeading(localState.view === "results" ? "mood-results-title" : "mood-title");
  const generation = ++moodMatchGeneration;
  void prepareMoodCandidates().then(() => {
    if (generation !== moodMatchGeneration || !localState.open) return;
    renderMoodMatch();
  });
}

function closeMoodMatch(restoreFocus = true, preserveDetailReturn = false) {
  const modal = find("mood-modal");
  if (!viewScope?.active) return;
  dialog.close(false); viewScope = null;
  modal.classList.add("hidden");
  document.body.classList.remove("mood-open");
  setMoodBackgroundInert(false);
  localState.open = false;
  localState.requestId += 1;
  moodMatchGeneration += 1;
  if (!preserveDetailReturn) localState.returnAfterDetail = false;
  if (isHome()) scheduleHomeHeroRotation();
  if (restoreFocus && moodMatchReturnFocus?.isConnected) moodMatchReturnFocus.focus();

}

function suspendMoodMatchForDetail() {
  localState.returnAfterDetail = true;
  closeMoodMatch(false, true);
}

function resumeMoodMatchAfterDetail() {
  const moodState = localState;
  if (!owner?.active || !moodState?.returnAfterDetail) return false;
  viewScope = dialog.open(moodMatchReturnFocus);
  view.mount(viewScope);
  moodState.returnAfterDetail = false;
  moodState.open = true;
  moodState.view = "results";
  const modal = find("mood-modal");
  modal.classList.remove("hidden");
  document.body.classList.add("mood-open");
  setMoodBackgroundInert(true);
  stopHomeHeroRotation();
  renderMoodMatchResults();
  viewScope?.frame(() => root.querySelector("#mood-lead .mood-lead-open")?.focus());
  return true;
}

function jumpMoodStep(index) {
  localState.requestId++;
  const moodState = localState;
  moodState.view = "question";
  moodState.step = Math.max(0, Math.min(MOOD_MATCH_STEPS.length - 1, Number(index) || 0));
  moodState.draftRefinements = null;
  renderMoodMatch();
  focusMoodHeading();
}

async function showMoodResults({ quick = false } = {}) {
  const moodState = localState;
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
  const next = find("mood-next");
  const quickButton = find("mood-quick");
  next.disabled = true;
  quickButton.disabled = true;
  next.textContent = "Der Schnitt wird geschärft …";
  moodSetText("mood-live-status", "Metadaten werden ergänzt. Harte Kriterien bleiben unangetastet.");
  const request = createScope();
  const active = viewScope;
  const release = active.add(() => request.dispose());
  try {
    await Promise.race([prepareMoodCandidates(request.signal), delay(8000, request.signal)]);
  } catch (error) { if (error.name !== "AbortError") throw error; }
  finally { release(); }
  if (!active.active) return;
  if (!moodState.open || requestId !== moodState.requestId) return;
  moodState.step = MOOD_MATCH_STEPS.length;
  moodState.view = "results";
  moodState.dismissed = [];
  quickButton.disabled = false;
  renderMoodMatchResults({ focus: true });
}

async function moodMatchNext() {
  const moodState = localState;
  if (moodState.view === "results") {
    localState = createMoodState();
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
  const moodState = localState;
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
  const lead = localState.analysis[0];
  if (!lead) return;
  localState.dismissed.push(homeEntryKey(lead.entry));
  renderMoodMatchResults();
  viewScope?.frame(() => root.querySelector("#mood-lead .mood-lead-open")?.focus());
}

function handleMoodMatchKeydown(event) {
  if (!localState.open) return false;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    if (localState.view === "refine") closeMoodRefinement(false);
    else closeMoodMatch();
    return true;
  }
  return false;
}

function mount() {
  if (owner?.active) return;
  owner = createScope();
  owner.listen(document, "click", event => {
    const trigger = event.target.closest?.("[data-mood-open]");
    if (trigger) openMoodMatch(trigger);
    if (event.target.closest?.("[data-mood-close]")) closeMoodMatch();
  });
  for (const [id, action] of [
    ["mood-back", moodMatchBack], ["mood-quick", moodMatchQuickResult],
    ["mood-refine-toggle", openMoodRefinement], ["mood-refine-reset", resetMoodRefinement],
    ["mood-refine-apply", () => closeMoodRefinement(true)],
    ["mood-genre-toggle", toggleMoodGenreCompass], ["mood-genre-clear", clearMoodGenreFocus],
    ["mood-next", moodMatchNext],
  ]) owner.listen(find(id), "click", action);
  owner.listen(root, "keydown", handleMoodMatchKeydown);
}
function unmount() {
  closeMoodMatch(false); localState.returnAfterDetail = false;
  owner?.dispose(); owner = null;
}
return { mount, unmount, open: openMoodMatch, close: closeMoodMatch, resumeAfterDetail: resumeMoodMatchAfterDetail };
}
