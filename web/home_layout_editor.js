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

function updateHomeRailNavigation(track) {
  if (!track?.id) return;
  const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
  const canScroll = maxScroll > 2;
  const atStart = track.scrollLeft <= 2;
  const atEnd = track.scrollLeft >= maxScroll - 2;
  document.querySelectorAll(`[data-home-scroll="${track.id}"]`).forEach((button) => {
    const direction = Number(button.dataset.direction) || 1;
    button.hidden = !canScroll || (direction < 0 ? atStart : atEnd);
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
  const direction = Number(button.dataset.direction) || 1;
  const distance = Math.max(280, track.clientWidth * 0.82);
  const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
  const target = Math.max(0, Math.min(track.scrollLeft + direction * distance, maximum));
  state.home.railScrollTargets ||= {};
  state.home.railScrollPositions ||= {};
  // Das Ziel muss vor dem asynchronen Smooth-Scroll feststehen. Andernfalls
  // kann ein Poster-Update im selben Frame noch den alten Wert 0 konservieren.
  state.home.railScrollTargets[track.id] = target;
  state.home.railScrollPositions[track.id] = target;
  track.scrollTo({ left: target, behavior: "smooth" });
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
    rememberHomeRailScroll(track);
    updateHomeRailNavigation(track);
  }, true);
  home.addEventListener("wheel", (event) => {
    const track = event.target.closest?.(".home-track");
    if (!track?.id) return;
    delete state.home.railScrollTargets?.[track.id];
  }, { passive: true, capture: true });
  home.addEventListener("pointerdown", (event) => {
    const track = event.target.closest?.(".home-track");
    if (!track?.id || event.target.closest?.("[data-home-scroll]")) return;
    delete state.home.railScrollTargets?.[track.id];
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
  layout.rail_order.forEach((railId) => {
    const section = document.querySelector(`[data-home-rail="${railId}"]`);
    if (!section) return;
    section.classList.toggle("home-layout-hidden", hidden.has(railId));
    section.setAttribute("aria-hidden", String(hidden.has(railId)));
    container?.appendChild(section);
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
    ...homeAllEntries(),
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
