import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { createDialog } from "../../shared/components/dialog.js";
import { HOME_RAIL_CATALOG, defaultHomeLayout, normalizeHomeLayout } from "./layout-model.js";

export function createHomeLayout(root, modal, { client = api, carousel, render, stopRotation }) {
  const document = root.ownerDocument;
  const find = id => root.querySelector(`#${id}`) || modal.querySelector(`#${id}`);
  const homeRailStoredScroll = (...args) => carousel.homeRailStoredScroll(...args);
  const restoreHomeRailScroll = (...args) => carousel.restoreHomeRailScroll(...args);
  const stopHomeHeroRotation = stopRotation;
  const renderHome = () => { if (scope?.active) render(); };
  let savedLayout = null, draftLayout = null, loaded = false, saving = false;
  let scope = null, rows = null, editor = null, pending = null;
  const dialog = createDialog(modal, {
    initialFocus: () => find("home-layout-close"),
    onClose() {
      if (saving) loaded = false; // The server may already have committed an aborted write.
      saving = false; editor = null;
      rows?.dispose(); rows = null;
      draftLayout = null;
      find("home-layout-save").disabled = false;
      modal.hidden = true;
      document.body.classList.remove("home-layout-editor-open");
      renderHome();
    },
  });
  function currentHomeLayout() {
    return normalizeHomeLayout(draftLayout || savedLayout || defaultHomeLayout());
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
    const container = root.querySelector(".home-rails");
    if (!container) return;
    HOME_RAIL_CATALOG.forEach((definition) => {
      const track = find(definition.trackId);
      const section = track?.closest(".home-rail") || createHomeRailElement(definition);
      section.dataset.homeRail = definition.id;
      if (!section.isConnected) container.appendChild(section);
    });
  }

  function applyHomeLayout() {
    ensureHomeRailElements();
    const layout = currentHomeLayout();
    const hidden = new Set(layout.hidden_rails);
    const container = root.querySelector(".home-rails");
    let cursor = container?.firstElementChild || null;
    layout.rail_order.forEach((railId, index) => {
      const section = root.querySelector(`[data-home-rail="${railId}"]`);
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
    const hero = find("home-hero");
    hero?.classList.toggle("home-layout-hidden", !layout.hero_visible);
    if (!layout.hero_visible) stopHomeHeroRotation();
  }

  async function loadHomeLayout() {
    if (!scope?.active || loaded) return;
    if (pending) return pending;
    const mounted = scope;
    pending = (async () => {
      try {
        const result = await client.get("/api/home/layout", { signal: mounted.signal });
        if (!mounted.active) return;
        savedLayout = normalizeHomeLayout(result);
        loaded = true;
        renderHome();
      } catch (error) {
        if (mounted.active) console.warn("Startseiten-Layout konnte nicht geladen werden:", error);
      } finally { if (scope === mounted) pending = null; }
    })();
    return pending;
  }

  function setHomeLayoutStatus(message, error = false) {
    const status = find("home-layout-status");
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
    draftLayout = layout;
    renderHomeLayoutEditor();
    renderHome();
  }

  function renderHomeLayoutEditor() {
    rows?.dispose(); rows = createScope();
    const list = find("home-layout-list");
    const count = find("home-layout-count");
    const heroToggle = find("home-layout-hero");
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
        rows.listen(button, "click", () => moveHomeLayoutRail(railId, offset));
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
      rows.listen(checkbox, "change", () => {
        const draft = currentHomeLayout();
        const nextHidden = new Set(draft.hidden_rails);
        if (checkbox.checked) nextHidden.delete(railId); else nextHidden.add(railId);
        if (nextHidden.size === HOME_RAIL_CATALOG.length) {
          checkbox.checked = true;
          setHomeLayoutStatus("Mindestens eine Reihe muss sichtbar bleiben.", true);
          return;
        }
        draft.hidden_rails = draft.rail_order.filter((id) => nextHidden.has(id));
        draftLayout = draft;
        renderHomeLayoutEditor();
        renderHome();
      });
      controls.appendChild(toggle);
      row.append(handle, position, copy, controls);
      rows.listen(row, "dragstart", (event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", railId);
        row.classList.add("is-dragging");
      });
      rows.listen(row, "dragend", () => row.classList.remove("is-dragging"));
      rows.listen(row, "dragover", (event) => { event.preventDefault(); row.classList.add("is-drop-target"); });
      rows.listen(row, "dragleave", () => row.classList.remove("is-drop-target"));
      rows.listen(row, "drop", (event) => {
        event.preventDefault();
        row.classList.remove("is-drop-target");
        const sourceId = event.dataTransfer.getData("text/plain");
        const draft = currentHomeLayout();
        const sourceIndex = draft.rail_order.indexOf(sourceId);
        const targetIndex = draft.rail_order.indexOf(railId);
        if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return;
        draft.rail_order.splice(targetIndex, 0, draft.rail_order.splice(sourceIndex, 1)[0]);
        draftLayout = draft;
        renderHomeLayoutEditor();
        renderHome();
      });
      list.appendChild(row);
    });
    count.textContent = `${HOME_RAIL_CATALOG.length - hidden.size} von ${HOME_RAIL_CATALOG.length} Reihen sichtbar`;
  }

  async function openHomeLayoutEditor(trigger) {
    if (!scope?.active || editor?.active) return;
    const mounted = scope;
    await loadHomeLayout();
    if (!mounted.active || editor?.active) return;
    draftLayout = normalizeHomeLayout(savedLayout || defaultHomeLayout());
    renderHomeLayoutEditor(); renderHome();
    modal.hidden = false;
    document.body.classList.add("home-layout-editor-open");
    setHomeLayoutStatus(loaded ? "Änderungen erscheinen sofort als Vorschau." : "Layout konnte nicht geladen werden. Erneut öffnen, um es erneut zu versuchen.", !loaded);
    editor = dialog.open(trigger);
  }

  function closeHomeLayoutEditor() { dialog.close(); }

  async function saveHomeLayoutEditor() {
    if (saving || !editor?.active) return;
    if (!loaded) { setHomeLayoutStatus("Layout zuerst erneut laden.", true); return; }
    saving = true;
    const active = editor;
    const submittedDraft = draftLayout;
    const button = find("home-layout-save");
    button.disabled = true;
    setHomeLayoutStatus("Startseite wird gespeichert …");
    try {
      const result = await client.put("/api/home/layout", currentHomeLayout(), { signal: active.signal });
      if (!active.active) return;
      savedLayout = normalizeHomeLayout(result);
      saving = false;
      if (draftLayout === submittedDraft) closeHomeLayoutEditor();
      else setHomeLayoutStatus("Gespeichert. Neuere Änderungen sind noch nicht gespeichert.");
    } catch (error) {
      if (active.active) setHomeLayoutStatus(`Speichern nicht möglich: ${error.message}`, true);
    } finally {
      if (active.active) { saving = false; button.disabled = false; }
    }
  }

  function mount() {
    if (scope?.active) return;
    scope = createScope();
    ensureHomeRailElements();
    scope.listen(find("home-layout-open"), "click", (event) => openHomeLayoutEditor(event.currentTarget));
    scope.listen(find("home-layout-close"), "click", () => closeHomeLayoutEditor());
    scope.listen(find("home-layout-cancel"), "click", () => closeHomeLayoutEditor());
    scope.listen(find("home-layout-save"), "click", saveHomeLayoutEditor);
    scope.listen(find("home-layout-reset"), "click", () => {
      draftLayout = defaultHomeLayout();
      renderHomeLayoutEditor(); renderHome();
      setHomeLayoutStatus("Standardanordnung als Vorschau geladen.");
    });
    scope.listen(find("home-layout-hero"), "change", (event) => {
      const draft = currentHomeLayout();
      draft.hero_visible = event.currentTarget.checked;
      draftLayout = draft;
      renderHome();
    });
    void loadHomeLayout();
  }

function unmount() {
  scope?.dispose(); scope = null; pending = null;
  dialog.unmount(); rows?.dispose(); rows = null;
}
return { definition: homeRailDefinition, mount, unmount, refresh: loadHomeLayout, current: currentHomeLayout, apply: applyHomeLayout, open: openHomeLayoutEditor, close: closeHomeLayoutEditor };
}
