const HOME_RAIL_CATALOG = [
  { id: "personal", trackId: "home-movies-track", title: "Für dich ausgewählt", eyebrow: "Persönlich", description: "Aus deinen Klicks, Downloads und Favoriten.", layout: "spotlight" },
  { id: "top", trackId: "home-top-track", title: "Top 10", eyebrow: "Tageschart", description: "Was heute über alle Quellen hinweg gefragt ist.", ranked: true },
  { id: "series", trackId: "home-series-track", title: "Serien, die gerade alle sehen", eyebrow: "Serien", description: "Aktuell beliebte Serien aus deinen Quellen." },
  { id: "genre", trackId: "home-genre-track", title: "Ein Genre für dich", eyebrow: "Geschmack", description: "Eine wechselnde Reihe aus deinen Lieblingsgenres." },
  { id: "explore", trackId: "home-explore-track", title: "Heute mal etwas anderes", eyebrow: "Entdecken", description: "Bewusst außerhalb deiner üblichen Auswahl." },
  { id: "gems", trackId: "home-gems-track", title: "Verborgene Schätze", eyebrow: "Geheimtipps", description: "Gut bewertete Titel abseits der Tagescharts." },
  { id: "fresh", trackId: "home-new-track", title: "Neu hinzugefügt", eyebrow: "Gemischt", description: "Neue Filme und Serien in einer Reihe." },
  { id: "new_movies", trackId: "home-new-movies-track", title: "Neue Filme", eyebrow: "Filme", description: "Die neuesten Filme aus allen aktiven Quellen." },
  { id: "new_series", trackId: "home-new-series-track", title: "Neue Serien", eyebrow: "Serien", description: "Neue und frisch aktualisierte Serien." },
  { id: "high_rated", trackId: "home-high-rated-track", title: "Besonders gut bewertet", eyebrow: "Bewertungen", description: "Filme und Serien mit starken Bewertungen." },
  { id: "movies", trackId: "home-movie-night-track", title: "Filmabend", eyebrow: "Nur Filme", description: "Eine täglich neu gemischte Auswahl nur mit Filmen." },
  { id: "library", trackId: "home-library-track", title: "Schon in deiner Mediathek", eyebrow: "Jellyfin", description: "Direkter Zugriff auf bereits vorhandene Titel." },
];
const HOME_DEFAULT_VISIBLE_RAILS = ["personal", "top", "series", "genre", "explore", "gems", "fresh"];
const HOME_RAIL_SCROLL_STEP_RATIO = 0.68;
const HOME_RAIL_WHEEL_FACTOR = 0.78;
const homeRailSettleTimers = new WeakMap();

function setHomeRailCycleAccessibility(element, cycle) {
  const interactive = element.querySelectorAll?.("a, button, input, select, textarea, [tabindex]") || [];
  const duplicate = cycle !== 1;
  if (duplicate) element.setAttribute?.("aria-hidden", "true");
  else element.removeAttribute?.("aria-hidden");
  interactive.forEach((control) => {
    if (duplicate) {
      if (!control.hasAttribute("data-home-loop-tabindex")) {
        control.setAttribute("data-home-loop-tabindex", control.getAttribute("tabindex") ?? "");
      }
      control.setAttribute("tabindex", "-1");
    } else if (control.hasAttribute("data-home-loop-tabindex")) {
      const previous = control.getAttribute("data-home-loop-tabindex");
      if (previous) control.setAttribute("tabindex", previous);
      else control.removeAttribute("tabindex");
      control.removeAttribute("data-home-loop-tabindex");
    }
  });
}

function homeRailLoopSize(track) {
  const count = Number(track?.dataset?.homeLoopCount || 0);
  if (!track || count < 2) return 0;
  const first = track.children[0];
  const repeated = track.children[count];
  const measured = Number(repeated?.offsetLeft) - Number(first?.offsetLeft);
  return measured > 0 ? measured : track.scrollWidth / 3;
}

function normalizeHomeRailLoop(track, { forceMiddle = false } = {}) {
  const size = homeRailLoopSize(track);
  if (!size) return 0;
  let next = track.scrollLeft;
  if (forceMiddle && next < size * 0.5) next += size;
  while (next < size * 0.2) next += size;
  while (next > size * 1.8) next -= size;
  if (Math.abs(next - track.scrollLeft) > 1) track.scrollLeft = next;
  return size;
}

function prepareHomeRailLoop(track, logicalCount) {
  if (!track) return;
  track.dataset ||= {};
  const wasLooping = Number(track.dataset.homeLoopCount || 0) > 1;
  track.dataset.homeLoopCount = logicalCount > 1 ? String(logicalCount) : "0";
  if (logicalCount < 2) {
    if (wasLooping) {
      track.scrollLeft = 0;
      delete state.home.railScrollPositions?.[track.id];
      delete state.home.railScrollTargets?.[track.id];
    }
    delete track.dataset.homeLoopReady;
    return;
  }
  const position = () => {
    if (track.dataset.homeLoopReady !== "true") {
      normalizeHomeRailLoop(track, { forceMiddle: true });
      track.dataset.homeLoopReady = "true";
    } else {
      normalizeHomeRailLoop(track);
    }
  };
  position();
  requestAnimationFrame(position);
}

function updateHomeRailNavigation(track) {
  if (!track?.id) return;
  const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
  const canScroll = maxScroll > 2;
  const looping = Number(track.dataset.homeLoopCount || 0) > 1;
  const atStart = track.scrollLeft <= 2;
  const atEnd = track.scrollLeft >= maxScroll - 2;
  document.querySelectorAll(`[data-home-scroll="${track.id}"]`).forEach((button) => {
    const direction = Number(button.dataset.direction) || 1;
    button.hidden = !canScroll || (!looping && (direction < 0 ? atStart : atEnd));
  });
}

function homeRailStoredScroll(track, fallback = 0) {
  const target = Number(state.home.railScrollTargets?.[track.id]);
  if (Number.isFinite(target)) return target;
  const stored = Number(state.home.railScrollPositions?.[track.id]);
  return Number.isFinite(stored) ? stored : fallback;
}

function rememberHomeRailScroll(track, { force = false } = {}) {
  if (!track?.id) return;
  state.home.railScrollPositions ||= {};
  state.home.railScrollTargets ||= {};
  const target = Number(state.home.railScrollTargets[track.id]);
  if (!force && Number.isFinite(target)) {
    if (Math.abs(track.scrollLeft - target) <= 3) {
      state.home.railScrollPositions[track.id] = track.scrollLeft;
      delete state.home.railScrollTargets[track.id];
    }
    return;
  }
  state.home.railScrollPositions[track.id] = track.scrollLeft;
}

function rememberAllHomeRailScroll() {
  document.querySelectorAll("#tab-home .home-track").forEach((track) => rememberHomeRailScroll(track));
}

function restoreHomeRailScroll(track, scrollLeft = 0) {
  const desired = homeRailStoredScroll(track, scrollLeft);
  const restore = () => {
    const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
    track.scrollLeft = Math.max(0, Math.min(desired, maximum));
    updateHomeRailNavigation(track);
  };
  restore();
  requestAnimationFrame(restore);
}

function moveHomeRail(button) {
  const track = document.getElementById(button.dataset.homeScroll);
  if (!track) return;
  normalizeHomeRailLoop(track, { forceMiddle: true });
  const direction = Number(button.dataset.direction) || 1;
  const distance = Math.max(260, track.clientWidth * HOME_RAIL_SCROLL_STEP_RATIO);
  const requested = track.scrollLeft + direction * distance;
  const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
  const target = homeRailLoopSize(track)
    ? requested
    : Math.max(0, Math.min(requested, maximum));
  state.home.railScrollTargets ||= {};
  state.home.railScrollPositions ||= {};
  // Das Ziel muss vor dem asynchronen Smooth-Scroll feststehen. Andernfalls
  // kann ein Poster-Update im selben Frame noch den alten Wert 0 konservieren.
  state.home.railScrollTargets[track.id] = target;
  state.home.railScrollPositions[track.id] = target;
  track.dataset.homeLoopAnimating = "true";
  const reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  track.scrollTo({ left: target, behavior: reducedMotion ? "auto" : "smooth" });
  scheduleHomeRailSettle(track, 700);
}

function scheduleHomeRailSettle(track, delay = 140) {
  const previous = homeRailSettleTimers.get(track);
  if (previous) clearTimeout(previous);
  const timer = window.setTimeout(() => {
    homeRailSettleTimers.delete(track);
    delete track.dataset.homeLoopAnimating;
    normalizeHomeRailLoop(track);
    delete state.home.railScrollTargets?.[track.id];
    rememberHomeRailScroll(track, { force: true });
  }, delay);
  homeRailSettleTimers.set(track, timer);
}

function initHomeRailScrolling() {
  const home = document.getElementById("tab-home");
  home.addEventListener("click", (event) => {
    const button = event.target.closest("[data-home-scroll]");
    if (button) moveHomeRail(button);
  });
  home.addEventListener("scroll", (event) => {
    const track = event.target.closest?.(".home-track");
    if (!track) return;
    if (track.dataset.homeLoopAnimating === "true") scheduleHomeRailSettle(track);
    else normalizeHomeRailLoop(track);
    rememberHomeRailScroll(track);
    updateHomeRailNavigation(track);
  }, true);
  home.addEventListener("wheel", (event) => {
    const track = event.target.closest?.(".home-track");
    if (!track?.id) return;
    delete state.home.railScrollTargets?.[track.id];
    const horizontalDelta = Math.abs(event.deltaX) > Math.abs(event.deltaY)
      ? event.deltaX
      : event.shiftKey ? event.deltaY : 0;
    if (!horizontalDelta) return;
    event.preventDefault();
    track.scrollLeft += horizontalDelta * HOME_RAIL_WHEEL_FACTOR;
    normalizeHomeRailLoop(track);
  }, { passive: false, capture: true });
  home.addEventListener("pointerdown", (event) => {
    const track = event.target.closest?.(".home-track");
    if (!track?.id || event.target.closest?.("[data-home-scroll]")) return;
    delete state.home.railScrollTargets?.[track.id];
    normalizeHomeRailLoop(track, { forceMiddle: true });
  }, true);
}

function defaultHomeLayout() {
  return {
    version: 1, hero_visible: true,
    rail_order: HOME_RAIL_CATALOG.map((rail) => rail.id),
    hidden_rails: HOME_RAIL_CATALOG.map((rail) => rail.id)
      .filter((railId) => !HOME_DEFAULT_VISIBLE_RAILS.includes(railId)),
  };
}

function normalizeHomeLayout(value) {
  const source = value && typeof value === "object" ? value : {};
  const allowed = new Set(HOME_RAIL_CATALOG.map((rail) => rail.id));
  const order = [];
  for (const raw of Array.isArray(source.rail_order) ? source.rail_order : []) {
    const railId = String(raw || "");
    if (allowed.has(railId) && !order.includes(railId)) order.push(railId);
  }
  HOME_RAIL_CATALOG.forEach((rail) => { if (!order.includes(rail.id)) order.push(rail.id); });
  const hidden = new Set((Array.isArray(source.hidden_rails) ? source.hidden_rails : [])
    .filter((railId) => allowed.has(railId)));
  if (hidden.size === allowed.size) hidden.delete(order[0]);
  return {
    version: 1, hero_visible: source.hero_visible !== false, rail_order: order,
    hidden_rails: order.filter((railId) => hidden.has(railId)),
  };
}

function currentHomeLayout() {
  return normalizeHomeLayout(state.home.layoutDraft || state.home.layout || defaultHomeLayout());
}

function homeRailDefinition(railId) {
  return HOME_RAIL_CATALOG.find((rail) => rail.id === railId);
}

function createHomeRailElement(definition) {
  const section = document.createElement("section");
  section.className = "home-rail home-layout-optional-rail";
  section.dataset.homeRail = definition.id;
  section.setAttribute("aria-labelledby", `${definition.trackId}-title`);
  const header = document.createElement("header");
  header.className = "home-rail-head";
  const copy = document.createElement("div");
  const eyebrow = document.createElement("span");
  eyebrow.className = "home-rail-eyebrow";
  eyebrow.textContent = definition.eyebrow;
  const title = document.createElement("h2");
  title.id = `${definition.trackId}-title`;
  title.textContent = definition.title;
  copy.append(eyebrow, title);
  const controls = document.createElement("div");
  controls.className = "home-rail-controls";
  [-1, 1].forEach((direction) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.homeScroll = definition.trackId;
    button.dataset.direction = String(direction);
    button.setAttribute("aria-label", `${definition.title} nach ${direction < 0 ? "links" : "rechts"} scrollen`);
    button.textContent = direction < 0 ? "‹" : "›";
    controls.appendChild(button);
  });
  header.append(copy, controls);
  const track = document.createElement("div");
  track.id = definition.trackId;
  track.className = "home-track";
  track.setAttribute("role", "group");
  track.setAttribute("aria-label", definition.title);
  section.append(header, track);
  return section;
}

function ensureHomeRailElements() {
  const container = document.querySelector("#tab-home .home-rails");
  if (!container) return;
  HOME_RAIL_CATALOG.forEach((definition) => {
    const track = document.getElementById(definition.trackId);
    const section = track?.closest(".home-rail") || createHomeRailElement(definition);
    section.dataset.homeRail = definition.id;
    if (!section.isConnected) container.appendChild(section);
  });
}

function applyHomeLayout() {
  ensureHomeRailElements();
  const layout = currentHomeLayout();
  const hidden = new Set(layout.hidden_rails);
  const container = document.querySelector("#tab-home .home-rails");
  let cursor = container?.firstElementChild || null;
  layout.rail_order.forEach((railId, index) => {
    const section = document.querySelector(`[data-home-rail="${railId}"]`);
    if (!section) return;
    // Die gespeicherte Reihenfolge ist die einzige Quelle der Wahrheit. Ein
    // expliziter Wert verhindert, dass alte oder spezifischere Styles einzelne
    // Reihen (insbesondere dynamisch erzeugte) vor die gewählte Position setzen.
    section.style.order = String(index);
    section.classList.toggle("home-layout-hidden", hidden.has(railId));
    section.setAttribute("aria-hidden", String(hidden.has(railId)));
    // Ein bereits korrekt einsortierter Abschnitt darf bei Daten-Updates nicht
    // erneut in den DOM eingehängt werden. Das erneute appendChild setzte in
    // Chromium den horizontalen Scroll-Container sichtbar auf den Anfang.
    if (container && section !== cursor) {
      const track = section.querySelector(".home-track");
      const scrollLeft = homeRailStoredScroll(track, track?.scrollLeft || 0);
      container.insertBefore(section, cursor);
      if (track) restoreHomeRailScroll(track, scrollLeft);
    }
    cursor = section.nextElementSibling;
  });
  const hero = document.getElementById("home-hero");
  hero?.classList.toggle("home-layout-hidden", !layout.hero_visible);
  if (!layout.hero_visible) stopHomeHeroRotation();
}

function homeRatedEntries() {
  return uniqueHomeEntries(homeAllEntries())
    .filter((entry) => Number(homeEntryMedia(entry).rating || 0) >= 7)
    .sort((left, right) => Number(homeEntryMedia(right).rating || 0) - Number(homeEntryMedia(left).rating || 0))
    .slice(0, 24);
}

function homeLibraryEntries() {
  return uniqueHomeEntries(homeAllEntries())
    .filter((entry) => state.home.jellyfinStatusByKey.get(homeEntryKey(entry)) === "owned"
      || mediaJellyfinStatus(homeEntryMedia(entry)) === "owned")
    .slice(0, 24);
}

function homeArtworkEntriesInLayout() {
  const lanes = homeDiscoveryLanes();
  const hidden = new Set(currentHomeLayout().hidden_rails);
  return uniqueHomeEntries([
    ...currentHomeLayout().rail_order
      .filter((railId) => !hidden.has(railId))
      .flatMap((railId) => lanes[railId] || []),
    ...homeHeroCandidates(),
  ]);
}

async function loadHomeLayout() {
  try {
    state.home.layout = normalizeHomeLayout(await api.homeLayout());
  } catch (error) {
    console.warn("Startseiten-Layout konnte nicht geladen werden:", error);
    state.home.layout = defaultHomeLayout();
  }
  state.home.layoutLoaded = true;
  if (state.tab === "home") renderHome();
}

function setHomeLayoutStatus(message, error = false) {
  const status = document.getElementById("home-layout-status");
  if (!status) return;
  status.textContent = message;
  status.classList.toggle("is-error", error);
}

function moveHomeLayoutRail(railId, offset) {
  const layout = currentHomeLayout();
  const index = layout.rail_order.indexOf(railId);
  const target = Math.max(0, Math.min(layout.rail_order.length - 1, index + offset));
  if (index < 0 || index === target) return;
  layout.rail_order.splice(target, 0, layout.rail_order.splice(index, 1)[0]);
  state.home.layoutDraft = layout;
  renderHomeLayoutEditor();
  renderHome();
}

function renderHomeLayoutEditor() {
  const list = document.getElementById("home-layout-list");
  const count = document.getElementById("home-layout-count");
  const heroToggle = document.getElementById("home-layout-hero");
  if (!list || !count || !heroToggle) return;
  const layout = currentHomeLayout();
  const hidden = new Set(layout.hidden_rails);
  heroToggle.checked = layout.hero_visible;
  list.replaceChildren();
  layout.rail_order.forEach((railId, index) => {
    const definition = homeRailDefinition(railId);
    if (!definition) return;
    const row = document.createElement("article");
    row.className = `home-layout-row${hidden.has(railId) ? " is-hidden" : ""}`;
    row.draggable = true;
    row.dataset.railId = railId;
    const handle = document.createElement("span");
    handle.className = "home-layout-handle";
    handle.textContent = "⠿";
    handle.setAttribute("aria-hidden", "true");
    const position = document.createElement("span");
    position.className = "home-layout-position";
    position.textContent = String(index + 1).padStart(2, "0");
    const copy = document.createElement("div");
    copy.className = "home-layout-row-copy";
    const heading = document.createElement("strong");
    heading.textContent = definition.title;
    const description = document.createElement("span");
    description.textContent = definition.description;
    copy.append(heading, description);
    const controls = document.createElement("div");
    controls.className = "home-layout-row-controls";
    [-1, 1].forEach((offset) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "home-layout-move";
      button.disabled = offset < 0 ? index === 0 : index === layout.rail_order.length - 1;
      button.setAttribute("aria-label", `${definition.title} nach ${offset < 0 ? "oben" : "unten"}`);
      button.textContent = offset < 0 ? "↑" : "↓";
      button.addEventListener("click", () => moveHomeLayoutRail(railId, offset));
      controls.appendChild(button);
    });
    const toggle = document.createElement("label");
    toggle.className = "home-layout-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = !hidden.has(railId);
    checkbox.setAttribute("aria-label", `${definition.title} anzeigen`);
    const switcher = document.createElement("span");
    switcher.setAttribute("aria-hidden", "true");
    toggle.append(checkbox, switcher);
    checkbox.addEventListener("change", () => {
      const draft = currentHomeLayout();
      const nextHidden = new Set(draft.hidden_rails);
      if (checkbox.checked) nextHidden.delete(railId); else nextHidden.add(railId);
      if (nextHidden.size === HOME_RAIL_CATALOG.length) {
        checkbox.checked = true;
        setHomeLayoutStatus("Mindestens eine Reihe muss sichtbar bleiben.", true);
        return;
      }
      draft.hidden_rails = draft.rail_order.filter((id) => nextHidden.has(id));
      state.home.layoutDraft = draft;
      renderHomeLayoutEditor();
      renderHome();
    });
    controls.appendChild(toggle);
    row.append(handle, position, copy, controls);
    row.addEventListener("dragstart", (event) => {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", railId);
      row.classList.add("is-dragging");
    });
    row.addEventListener("dragend", () => row.classList.remove("is-dragging"));
    row.addEventListener("dragover", (event) => { event.preventDefault(); row.classList.add("is-drop-target"); });
    row.addEventListener("dragleave", () => row.classList.remove("is-drop-target"));
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      row.classList.remove("is-drop-target");
      const sourceId = event.dataTransfer.getData("text/plain");
      const draft = currentHomeLayout();
      const sourceIndex = draft.rail_order.indexOf(sourceId);
      const targetIndex = draft.rail_order.indexOf(railId);
      if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return;
      draft.rail_order.splice(targetIndex, 0, draft.rail_order.splice(sourceIndex, 1)[0]);
      state.home.layoutDraft = draft;
      renderHomeLayoutEditor();
      renderHome();
    });
    list.appendChild(row);
  });
  count.textContent = `${HOME_RAIL_CATALOG.length - hidden.size} von ${HOME_RAIL_CATALOG.length} Reihen sichtbar`;
}

let homeLayoutEditorTrigger = null;

function openHomeLayoutEditor(trigger) {
  homeLayoutEditorTrigger = trigger || document.activeElement;
  state.home.layoutDraft = normalizeHomeLayout(state.home.layout || defaultHomeLayout());
  renderHomeLayoutEditor();
  renderHome();
  const modal = document.getElementById("home-layout-modal");
  modal.hidden = false;
  document.body.classList.add("home-layout-editor-open");
  setHomeLayoutStatus("Änderungen erscheinen sofort als Vorschau.");
  document.getElementById("home-layout-close")?.focus();
}

function closeHomeLayoutEditor({ keepDraft = false } = {}) {
  if (!keepDraft) state.home.layoutDraft = null;
  document.getElementById("home-layout-modal").hidden = true;
  document.body.classList.remove("home-layout-editor-open");
  renderHome();
  homeLayoutEditorTrigger?.focus?.();
}

async function saveHomeLayoutEditor() {
  if (state.home.layoutSaving) return;
  state.home.layoutSaving = true;
  const button = document.getElementById("home-layout-save");
  button.disabled = true;
  setHomeLayoutStatus("Startseite wird gespeichert …");
  try {
    state.home.layout = normalizeHomeLayout(await api.saveHomeLayout(currentHomeLayout()));
    state.home.layoutDraft = null;
    closeHomeLayoutEditor({ keepDraft: true });
  } catch (error) {
    setHomeLayoutStatus(`Speichern nicht möglich: ${error.message}`, true);
  } finally {
    state.home.layoutSaving = false;
    button.disabled = false;
  }
}

function trapHomeLayoutFocus(event, modal) {
  if (event.key === "Escape") { event.preventDefault(); closeHomeLayoutEditor(); return; }
  if (event.key !== "Tab") return;
  const focusable = [...modal.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((element) => element.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault(); last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault(); first.focus();
  }
}

function initHomeLayoutEditor() {
  ensureHomeRailElements();
  document.getElementById("home-layout-open")?.addEventListener("click", (event) => openHomeLayoutEditor(event.currentTarget));
  document.getElementById("home-layout-close")?.addEventListener("click", () => closeHomeLayoutEditor());
  document.getElementById("home-layout-cancel")?.addEventListener("click", () => closeHomeLayoutEditor());
  document.getElementById("home-layout-save")?.addEventListener("click", saveHomeLayoutEditor);
  document.getElementById("home-layout-reset")?.addEventListener("click", () => {
    state.home.layoutDraft = defaultHomeLayout();
    renderHomeLayoutEditor(); renderHome();
    setHomeLayoutStatus("Standardanordnung als Vorschau geladen.");
  });
  document.getElementById("home-layout-hero")?.addEventListener("change", (event) => {
    const draft = currentHomeLayout();
    draft.hero_visible = event.currentTarget.checked;
    state.home.layoutDraft = draft;
    renderHome();
  });
  const modal = document.getElementById("home-layout-modal");
  modal?.addEventListener("click", (event) => { if (event.target === modal) closeHomeLayoutEditor(); });
  modal?.addEventListener("keydown", (event) => trapHomeLayoutFocus(event, modal));
}
