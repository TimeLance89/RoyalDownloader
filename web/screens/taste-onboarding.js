const TASTE_ONBOARDING_MINIMUM = 5;
const TASTE_ONBOARDING_SIZE = 32;
let tasteOnboardingPage = 0;
let tasteOnboardingTimer = 0;
let tasteOnboardingBound = false;
let tasteOnboardingSelection = new Map();
let tasteOnboardingSeen = new Set();

function tasteOnboardingEntryData(entry) {
  const media = homeEntryMedia(entry);
  const year = String(media.year || media.release_date || media.first_air_date || "").match(/\b(19|20)\d{2}\b/)?.[0] || "";
  return {
    entry,
    key: homeEntryKey(entry),
    title: String(media.title || media.name || "").trim(),
    kind: entry.kind,
    year,
    decade: year ? `${year.slice(0, 3)}0` : "unknown",
    genres: [...new Set((media.genres || []).map((genre) => String(genre).trim()).filter(Boolean))],
    artwork: media.cover_url || media.poster_url || media.backdrop_url || "",
    metadata: tasteMetadata(entry.kind, media),
  };
}

function tasteOnboardingHash(value) {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function diverseTasteOnboardingCandidates(entries, page = 0) {
  const unique = new Map();
  entries.map(tasteOnboardingEntryData).forEach((item) => {
    if (item.key && item.title && item.artwork && !unique.has(item.key)) unique.set(item.key, item);
  });
  const pool = [...unique.values()].sort((a, b) =>
    tasteOnboardingHash(`${page}|${a.key}`) - tasteOnboardingHash(`${page}|${b.key}`));
  const selected = [];
  const genreCounts = new Map();
  const kindCounts = new Map();
  const decadeCounts = new Map();
  while (pool.length && selected.length < TASTE_ONBOARDING_SIZE) {
    let bestIndex = 0;
    let bestScore = -Infinity;
    pool.forEach((item, index) => {
      const unseenGenres = item.genres.filter((genre) => !genreCounts.has(genre)).length;
      const genrePressure = item.genres.reduce((sum, genre) => sum + (genreCounts.get(genre) || 0), 0);
      const score = unseenGenres * 8
        - genrePressure * 2.4
        - (kindCounts.get(item.kind) || 0) * 1.4
        - (decadeCounts.get(item.decade) || 0) * .55
        + ((tasteOnboardingHash(`${page}:${item.key}:tie`) % 1000) / 1000);
      if (score > bestScore) { bestScore = score; bestIndex = index; }
    });
    const [picked] = pool.splice(bestIndex, 1);
    selected.push(picked);
    picked.genres.forEach((genre) => genreCounts.set(genre, (genreCounts.get(genre) || 0) + 1));
    kindCounts.set(picked.kind, (kindCounts.get(picked.kind) || 0) + 1);
    decadeCounts.set(picked.decade, (decadeCounts.get(picked.decade) || 0) + 1);
  }
  return selected;
}

function updateTasteOnboardingProgress() {
  const count = tasteOnboardingSelection.size;
  document.getElementById("taste-onboarding-count").textContent = String(count);
  document.getElementById("taste-onboarding-submit").disabled = count < TASTE_ONBOARDING_MINIMUM;
  const selected = document.getElementById("taste-onboarding-selected");
  if (!selected) return;
  selected.replaceChildren(...[...tasteOnboardingSelection.values()].map((item) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "taste-onboarding-selection";
    chip.textContent = `${item.title} ×`;
    chip.setAttribute("aria-label", `${item.title} aus Auswahl entfernen`);
    chip.addEventListener("click", () => {
      tasteOnboardingSelection.delete(item.key);
      document.querySelector(`.taste-onboarding-card[data-key="${CSS.escape(item.key)}"]`)?.classList.remove("is-selected");
      document.querySelector(`.taste-onboarding-card[data-key="${CSS.escape(item.key)}"]`)?.setAttribute("aria-pressed", "false");
      updateTasteOnboardingProgress();
    });
    return chip;
  }));
}

function renderTasteOnboardingCandidates() {
  const grid = document.getElementById("taste-onboarding-grid");
  const status = document.getElementById("taste-onboarding-status");
  const allCandidates = diverseTasteOnboardingCandidates(homeAllEntries(), tasteOnboardingPage);
  let candidates = allCandidates.filter((item) => !tasteOnboardingSeen.has(item.key));
  if (!candidates.length && allCandidates.length) {
    tasteOnboardingSeen = new Set(tasteOnboardingSelection.keys());
    candidates = allCandidates.filter((item) => !tasteOnboardingSeen.has(item.key));
  }
  if (!candidates.length) {
    status.hidden = false;
    status.textContent = "Titel werden zusammengestellt …";
    clearTimeout(tasteOnboardingTimer);
    tasteOnboardingTimer = window.setTimeout(renderTasteOnboardingCandidates, 600);
    return;
  }
  candidates.forEach((item) => tasteOnboardingSeen.add(item.key));
  status.hidden = true;
  grid.replaceChildren(...candidates.map((item) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "taste-onboarding-card";
    card.dataset.key = item.key;
    const selected = tasteOnboardingSelection.has(item.key);
    card.classList.toggle("is-selected", selected);
    card.setAttribute("aria-pressed", String(selected));
    const image = document.createElement("img");
    image.src = item.artwork;
    image.alt = "";
    image.loading = "lazy";
    const shade = document.createElement("span");
    shade.className = "taste-onboarding-card-copy";
    const title = document.createElement("strong");
    title.textContent = item.title;
    const meta = document.createElement("small");
    meta.textContent = [item.kind === "movie" ? "Film" : item.kind === "anime" ? "Anime" : "Serie", item.year].filter(Boolean).join(" · ");
    const check = document.createElement("i");
    check.textContent = "✓";
    check.setAttribute("aria-hidden", "true");
    shade.append(title, meta);
    card.append(image, shade, check);
    card.addEventListener("click", () => {
      if (tasteOnboardingSelection.has(item.key)) tasteOnboardingSelection.delete(item.key);
      else tasteOnboardingSelection.set(item.key, item);
      const isSelected = tasteOnboardingSelection.has(item.key);
      card.classList.toggle("is-selected", isSelected);
      card.setAttribute("aria-pressed", String(isSelected));
      updateTasteOnboardingProgress();
    });
    return card;
  }));
}

async function completeTasteOnboarding() {
  if (tasteOnboardingSelection.size < TASTE_ONBOARDING_MINIMUM) return;
  const submit = document.getElementById("taste-onboarding-submit");
  const more = document.getElementById("taste-onboarding-more");
  const status = document.getElementById("taste-onboarding-status");
  submit.disabled = true;
  more.disabled = true;
  status.hidden = false;
  status.textContent = "Dein Royal-Profil wird vorbereitet …";
  try {
    const result = await api.tasteOnboarding([...tasteOnboardingSelection.values()].map((item) => ({
      item_key: item.key,
      title: item.title,
      media_type: item.kind,
      metadata: item.metadata,
    })));
    authStatus.user = result.user;
    applyServerTasteProfile(result.profile);
    state.ai.recommendations = [];
    state.ai.lastFingerprint = "";
    document.body.classList.remove("taste-onboarding-open");
    document.getElementById("taste-onboarding").classList.add("hidden");
    renderHome({ force: true });
    void window.refreshAiDiscovery?.(true);
  } catch (error) {
    status.textContent = error.message;
    submit.disabled = false;
    more.disabled = false;
  }
}

function initTasteOnboarding(status = authStatus) {
  const user = status?.user;
  const screen = document.getElementById("taste-onboarding");
  if (!screen || !user?.taste_onboarding_required) return false;
  document.getElementById("taste-onboarding-welcome").textContent = `Willkommen, ${user.display_name || user.username}.`;
  screen.classList.remove("hidden");
  document.body.classList.add("taste-onboarding-open");
  tasteOnboardingSelection = new Map();
  tasteOnboardingSeen = new Set();
  updateTasteOnboardingProgress();
  renderTasteOnboardingCandidates();
  if (!tasteOnboardingBound) {
    tasteOnboardingBound = true;
    document.getElementById("taste-onboarding-more").addEventListener("click", () => {
      tasteOnboardingPage += 1;
      renderTasteOnboardingCandidates();
    });
    document.getElementById("taste-onboarding-submit").addEventListener("click", completeTasteOnboarding);
  }
  return true;
}

function reopenTasteOnboarding(user) {
  if (!user) return;
  authStatus.user = user;
  initTasteOnboarding(authStatus);
}

window.initTasteOnboarding = initTasteOnboarding;
