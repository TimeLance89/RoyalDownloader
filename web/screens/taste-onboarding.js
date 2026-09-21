const TASTE_ONBOARDING_MINIMUM = 5;
const TASTE_ONBOARDING_BATCH_SIZE = 20;
let tasteOnboardingPage = 0;
let tasteOnboardingTimer = 0;
let tasteOnboardingBound = false;
let tasteOnboardingLoading = false;
let tasteOnboardingExhausted = false;
let tasteOnboardingScrollFrame = 0;
let tasteOnboardingSelection = new Map();
let tasteOnboardingSeen = new Set();
let tasteOnboardingPool = [];

function tasteOnboardingGenreName(genre) {
  return String(typeof genre === "object" ? genre?.name || genre?.label || "" : genre || "").trim();
}

function tasteOnboardingRuntime(value) {
  const minutes = Number(String(value || "").match(/\d+/)?.[0] || 0);
  if (!minutes) return "";
  if (minutes < 60) return `${minutes} Min.`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)} Std.${rest ? ` ${rest} Min.` : ""}`;
}

function tasteOnboardingEntryData(entry) {
  const media = homeEntryMedia(entry);
  const year = String(media.year || media.release_date || media.first_air_date || "").match(/\b(19|20)\d{2}\b/)?.[0] || "";
  const genres = [...new Set((media.genres || []).map(tasteOnboardingGenreName).filter(Boolean))];
  const rating = Number(media.rating || media.vote_average || media.score || 0);
  return {
    entry,
    key: homeEntryKey(entry),
    title: String(media.title || media.name || "").trim(),
    kind: entry.kind,
    kindLabel: entry.kind === "movie" ? "Film" : entry.kind === "anime" ? "Anime" : "Serie",
    year,
    decade: year ? `${year.slice(0, 3)}0` : "unknown",
    genres,
    artwork: media.cover_url || media.poster_url || media.backdrop_url || "",
    description: String(media.description || media.overview || media.synopsis || "").trim(),
    rating: Number.isFinite(rating) && rating > 0 ? Math.min(10, rating) : 0,
    runtime: tasteOnboardingRuntime(media.runtime || media.duration),
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
  while (pool.length) {
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

function refreshTasteOnboardingPool() {
  const seed = tasteOnboardingHash(String(authStatus?.user?.id || authStatus?.user?.username || "royal"));
  tasteOnboardingPool = diverseTasteOnboardingCandidates(homeAllEntries(), seed);
  tasteOnboardingExhausted = tasteOnboardingPool.every((item) => tasteOnboardingSeen.has(item.key));
  return tasteOnboardingPool;
}

function updateTasteOnboardingProgress() {
  const count = tasteOnboardingSelection.size;
  const progress = document.querySelector(".taste-onboarding-progress");
  document.getElementById("taste-onboarding-count").textContent = String(count);
  document.getElementById("taste-onboarding-submit").disabled = count < TASTE_ONBOARDING_MINIMUM;
  progress?.style.setProperty("--taste-progress", `${Math.min(100, count / TASTE_ONBOARDING_MINIMUM * 100)}%`);
  progress?.classList.toggle("is-ready", count >= TASTE_ONBOARDING_MINIMUM);
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

function createTasteOnboardingCard(item) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "taste-onboarding-card";
  card.dataset.key = item.key;
  const selected = tasteOnboardingSelection.has(item.key);
  card.classList.toggle("is-selected", selected);
  card.setAttribute("aria-pressed", String(selected));
  card.setAttribute("aria-label", `${item.title} auswählen`);

  const artwork = document.createElement("span");
  artwork.className = "taste-onboarding-card-art";
  const image = document.createElement("img");
  image.src = item.artwork;
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  const fallback = document.createElement("span");
  fallback.className = "taste-onboarding-card-fallback";
  fallback.textContent = item.title.slice(0, 1).toUpperCase();
  image.addEventListener("error", () => image.remove(), { once: true });

  const check = document.createElement("i");
  check.className = "taste-onboarding-check";
  check.textContent = "✓";
  check.setAttribute("aria-hidden", "true");
  artwork.append(fallback, image, check);

  const copy = document.createElement("span");
  copy.className = "taste-onboarding-card-copy";
  const facts = document.createElement("span");
  facts.className = "taste-onboarding-card-facts";
  [
    item.rating ? `★ ${item.rating.toFixed(1)}` : "",
    item.year,
    item.kindLabel,
    item.runtime,
  ].filter(Boolean).forEach((value, index) => {
    const fact = document.createElement("small");
    fact.textContent = value;
    if (index === 0 && item.rating) fact.className = "is-rating";
    facts.append(fact);
  });
  const title = document.createElement("strong");
  title.textContent = item.title;
  const genres = document.createElement("span");
  genres.className = "taste-onboarding-card-genres";
  genres.textContent = item.genres.slice(0, 3).join(" · ") || "Weitere Details folgen";
  copy.append(facts, title, genres);
  if (item.description) {
    const description = document.createElement("span");
    description.className = "taste-onboarding-card-description";
    description.textContent = item.description;
    copy.append(description);
  }
  card.append(artwork, copy);
  card.addEventListener("click", () => {
    if (tasteOnboardingSelection.has(item.key)) tasteOnboardingSelection.delete(item.key);
    else tasteOnboardingSelection.set(item.key, item);
    const isSelected = tasteOnboardingSelection.has(item.key);
    card.classList.toggle("is-selected", isSelected);
    card.setAttribute("aria-pressed", String(isSelected));
    card.setAttribute("aria-label", `${item.title} ${isSelected ? "ausgewählt" : "auswählen"}`);
    updateTasteOnboardingProgress();
  });
  return card;
}

function updateTasteOnboardingLoadState() {
  const more = document.getElementById("taste-onboarding-more");
  if (!more) return;
  more.disabled = tasteOnboardingLoading || (tasteOnboardingExhausted && tasteOnboardingPool.length > 0);
  more.textContent = tasteOnboardingLoading
    ? "Titel werden geladen …"
    : tasteOnboardingExhausted
      ? tasteOnboardingPool.length ? "Alle Titel angezeigt" : "Erneut laden"
      : "Weitere Titel laden";
}

function appendTasteOnboardingCandidates({ reveal = false } = {}) {
  if (tasteOnboardingLoading || tasteOnboardingExhausted) return 0;
  const grid = document.getElementById("taste-onboarding-grid");
  const status = document.getElementById("taste-onboarding-status");
  if (!grid || !status) return 0;
  tasteOnboardingLoading = true;
  updateTasteOnboardingLoadState();
  if (!tasteOnboardingPool.length) refreshTasteOnboardingPool();
  const candidates = tasteOnboardingPool
    .filter((item) => !tasteOnboardingSeen.has(item.key))
    .slice(0, TASTE_ONBOARDING_BATCH_SIZE);

  if (!candidates.length) {
    tasteOnboardingLoading = false;
    tasteOnboardingExhausted = tasteOnboardingPool.length > 0;
    status.hidden = tasteOnboardingExhausted;
    status.textContent = tasteOnboardingExhausted ? "" : "Titel werden zusammengestellt …";
    updateTasteOnboardingLoadState();
    if (!tasteOnboardingExhausted) {
      clearTimeout(tasteOnboardingTimer);
      tasteOnboardingTimer = window.setTimeout(() => {
        refreshTasteOnboardingPool();
        appendTasteOnboardingCandidates();
      }, 600);
    }
    return 0;
  }

  const fragment = document.createDocumentFragment();
  let firstNewCard = null;
  candidates.forEach((item) => {
    tasteOnboardingSeen.add(item.key);
    const card = createTasteOnboardingCard(item);
    firstNewCard ||= card;
    fragment.append(card);
  });
  grid.append(fragment);
  tasteOnboardingPage += 1;
  tasteOnboardingLoading = false;
  tasteOnboardingExhausted = tasteOnboardingPool.every((item) => tasteOnboardingSeen.has(item.key));
  status.hidden = true;
  updateTasteOnboardingLoadState();
  if (reveal && firstNewCard) firstNewCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return candidates.length;
}

function handleTasteOnboardingScroll() {
  if (tasteOnboardingScrollFrame) return;
  tasteOnboardingScrollFrame = window.requestAnimationFrame(() => {
    tasteOnboardingScrollFrame = 0;
    const grid = document.getElementById("taste-onboarding-grid");
    if (!grid || tasteOnboardingLoading || tasteOnboardingExhausted) return;
    const remaining = grid.scrollHeight - grid.scrollTop - grid.clientHeight;
    if (remaining < Math.max(520, grid.clientHeight * .7)) appendTasteOnboardingCandidates();
  });
}

async function loadTasteOnboardingCatalog() {
  const status = document.getElementById("taste-onboarding-status");
  const screen = document.getElementById("taste-onboarding");
  tasteOnboardingLoading = true;
  if (status) {
    status.hidden = false;
    status.textContent = "Dein Katalog wird geladen …";
  }
  updateTasteOnboardingLoadState();
  try {
    if (!state.home.loading && !state.home.refreshing && typeof loadHomeData === "function") {
      await loadHomeData();
    } else {
      const startedAt = Date.now();
      while ((state.home.loading || state.home.refreshing) && Date.now() - startedAt < 30000) {
        if (screen?.classList.contains("hidden")) return;
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
    }
  } catch (error) {
    console.warn("Katalog für die Geschmacksauswahl konnte nicht geladen werden:", error);
  }
  if (screen?.classList.contains("hidden")) return;
  tasteOnboardingLoading = false;
  refreshTasteOnboardingPool();
  if (tasteOnboardingPool.length) {
    tasteOnboardingExhausted = false;
    appendTasteOnboardingCandidates();
  } else {
    tasteOnboardingExhausted = true;
    if (status) {
      status.hidden = false;
      status.textContent = "Der Katalog ist gerade nicht verfügbar. Bitte versuche es gleich erneut.";
    }
    updateTasteOnboardingLoadState();
  }
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
  tasteOnboardingPage = 0;
  tasteOnboardingLoading = false;
  tasteOnboardingExhausted = false;
  tasteOnboardingSelection = new Map();
  tasteOnboardingSeen = new Set();
  tasteOnboardingPool = [];
  document.getElementById("taste-onboarding-grid").replaceChildren();
  updateTasteOnboardingProgress();
  if (homeAllEntries().length) appendTasteOnboardingCandidates();
  else void loadTasteOnboardingCatalog();

  if (typeof warmDiscoveryReservoirV2 === "function") {
    void warmDiscoveryReservoirV2().then(() => {
      if (screen.classList.contains("hidden")) return;
      refreshTasteOnboardingPool();
      if (tasteOnboardingPool.some((item) => !tasteOnboardingSeen.has(item.key))) tasteOnboardingExhausted = false;
      updateTasteOnboardingLoadState();
      handleTasteOnboardingScroll();
    });
  }

  if (!tasteOnboardingBound) {
    tasteOnboardingBound = true;
    document.getElementById("taste-onboarding-grid").addEventListener("scroll", handleTasteOnboardingScroll, { passive: true });
    document.getElementById("taste-onboarding-more").addEventListener("click", () => {
      if (tasteOnboardingExhausted && !tasteOnboardingPool.length) void loadTasteOnboardingCatalog();
      else appendTasteOnboardingCandidates({ reveal: true });
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
