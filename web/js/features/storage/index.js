import { installStorageUi } from "./layout.js";
import { createStorageView } from "./view.js";
import { escapeHtml as html } from "../../shared/utils/escape-html.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { createStorageApi } from "./api.js";
import { createStorageJobs } from "./jobs.js";
import { createStorageAutopilot } from "./autopilot.js";
import { formatBytes } from "../../shared/formatters/bytes.js";

export function createStorage(root) {
  const view = createStorageView(root);
  let scope;
  let shell;
  let statusRequest;
  let planGeneration = 0;
  const find = id => root.querySelector(`#${id}`);
  const jobs = createStorageJobs(root, { onCompleted() {
    void refreshStatus(false);
    if (scope?.active) scope.timeout(() => void scanStorage(), 250);
  } });

  const POLL_MS = 5000;
  let scanRunning = false;
  let editingLocationId = "";
  let currentLocations = [];
  let activeMove = null;

  function storageActive() {
    return root?.classList.contains("active")
      && find("settings-storage")?.classList.contains("is-active");
  }

  function activateStorage() {
    const target = find("settings-storage");
    const panel = root?.querySelector(".settings-panel");
    if (!target || !root || !panel) return;
    root.querySelectorAll("[data-settings-section]").forEach((section) => {
      const active = section === target;
      section.classList.toggle("is-active", active);
      section.hidden = !active;
      section.setAttribute("aria-hidden", active ? "false" : "true");
    });
    panel.classList.remove("is-overview");
    root.querySelectorAll(".settings-directory-nav [data-settings-target]").forEach((link) => {
      const active = link.dataset.settingsTarget === "settings-storage";
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    updateActivity();
  }

  function refreshStatus(silent = true) {
    if (!scope?.active) return Promise.resolve();
    if (statusRequest) return statusRequest;
    const request = loadStatus(silent).finally(() => { if (statusRequest === request) statusRequest = null; });
    statusRequest = request;
    return request;
  }
  async function loadStatus(silent) {
    const current = scope;
    if (!current?.active) return;
    const api = createStorageApi(current);
    const live = find("storage-live-state");
    if (!silent && live) live.textContent = "wird aktualisiert …";
    find("storage-summary").dataset.viewState = "loading";
    try {
      const payload = await api.get("/api/storage/status");
      if (!current.active) return;
      currentLocations = Array.isArray(payload.locations) ? payload.locations : [];
      await autopilot.refresh();
      if (!current.active) return;
      view.status({ ...payload, autopilot: autopilot.snapshot() });
    }
    catch (error) {
      if (!current.active || isAbortError(error)) return;
      find("storage-summary").dataset.viewState = "error";
      if (live) live.textContent = `Live-Abfrage fehlgeschlagen · ${error.message}`;
    }
  }

  function selectedLocationMediaTypes() {
    return [...root.querySelectorAll('input[name="storage-location-media"]:checked')].map((input) => input.value);
  }

  function syncLocationMediaFields({ selectDefaults = false } = {}) {
    const mode = find("storage-location-mode")?.value || "monitor";
    const group = find("storage-location-media-types");
    if (!group) return;
    const inputs = [...group.querySelectorAll('input[name="storage-location-media"]')];
    if (mode === "media" && selectDefaults && !inputs.some((input) => input.checked)) {
      inputs.forEach((input) => { input.checked = true; });
    }
    group.hidden = mode !== "media";
    inputs.forEach((input) => { input.disabled = mode !== "media"; });
  }

  function resetLocationForm() {
    editingLocationId = "";
    const form = find("storage-location-form");
    form?.reset();
    syncLocationMediaFields();
    const save = find("storage-location-save");
    const cancel = find("storage-location-cancel");
    if (save) save.textContent = "Speicherort hinzufügen";
    if (cancel) cancel.hidden = true;
  }

  function editLocation(locationId) {
    const location = currentLocations.find((item) => item.id === locationId);
    if (!location) return;
    editingLocationId = location.id;
    find("storage-location-label").value = location.label;
    find("storage-location-path").value = location.path;
    find("storage-location-mode").value = location.mode;
    const allowed = new Set(Array.isArray(location.media_types) ? location.media_types : ["movies", "series", "anime"]);
    root.querySelectorAll('input[name="storage-location-media"]').forEach((input) => {
      input.checked = allowed.has(input.value);
    });
    syncLocationMediaFields({ selectDefaults: location.mode === "media" });
    const save = find("storage-location-save");
    const cancel = find("storage-location-cancel");
    if (save) save.textContent = "Änderungen speichern";
    if (cancel) cancel.hidden = false;
    find("storage-location-label")?.focus();
  }

  async function saveLocation(event) {
    const current = scope;
    if (!current?.active) return;
    const api = createStorageApi(current);
    event.preventDefault();
    const label = find("storage-location-label")?.value.trim() || "";
    const path = find("storage-location-path")?.value.trim() || "";
    const mode = find("storage-location-mode")?.value || "monitor";
    const mediaTypes = mode === "media" ? selectedLocationMediaTypes() : [];
    const save = find("storage-location-save");
    const status = find("storage-cleanup-status");
    if (!label || !path) return;
    if (mode === "media" && !mediaTypes.length) {
      if (status) status.textContent = "Wähle mindestens eine Medienart aus: Filme, Serien oder Anime.";
      return;
    }
    if (save) { save.disabled = true; save.textContent = "Speichere …"; }
    try {
      await api.post("/api/storage/locations/save", {
        location_id: editingLocationId,
        label,
        path,
        mode,
        media_types: mediaTypes,
      });
      if (!current.active) return;
      if (status) status.textContent = `${label} gespeichert. Die Live-Werte werden neu eingelesen.`;
      resetLocationForm();
      if (current.active) await refreshStatus(false);
    } catch (error) { if (!current.active || isAbortError(error)) return;
      if (status) status.textContent = `Speicherort konnte nicht gespeichert werden · ${error.message}`;
    } finally {
      if (!current.active) return;
      if (save) { save.disabled = false; save.textContent = editingLocationId ? "Änderungen speichern" : "Speicherort hinzufügen"; }
    }
  }

  async function removeLocation(locationId) {
    const current = scope;
    if (!current?.active) return;
    const api = createStorageApi(current);
    const location = currentLocations.find((item) => item.id === locationId);
    if (!location) return;
    if (!window.confirm(`Speicherort „${location.label}“ aus Royal entfernen?\n\nEs werden keine Dateien gelöscht. Nur die Überwachung dieses Pfads wird entfernt.`)) return;
    const status = find("storage-cleanup-status");
    try {
      await api.post("/api/storage/locations/remove", { location_id: location.id });
      if (!current.active) return;
      if (editingLocationId === location.id) resetLocationForm();
      if (status) status.textContent = `${location.label} aus der Speicherüberwachung entfernt. Dateien wurden nicht verändert.`;
      if (current.active) await refreshStatus(false);
    } catch (error) { if (!current.active || isAbortError(error)) return;
      if (status) status.textContent = `Speicherort konnte nicht entfernt werden · ${error.message}`;
    }
  }

  function handleLocationAction(event) {
    const edit = event.target.closest("[data-location-edit]");
    if (edit) { editLocation(edit.dataset.locationEdit); return; }
    const remove = event.target.closest("[data-location-remove]");
    if (remove) void removeLocation(remove.dataset.locationRemove);
  }

  function candidateData(button) {
    return {
      root: button.dataset.root,
      relative_path: button.dataset.relativePath,
      token: button.dataset.token,
      expected_size: Number(button.dataset.size) || 0,
      expires_at: Number(button.dataset.expiresAt) || 0,
    };
  }

  async function scanStorage() {
    const current = scope;
    if (!current?.active) return;
    const api = createStorageApi(current);
    if (scanRunning) return;
    const button = find("storage-scan");
    const summary = find("storage-scan-summary");
    scanRunning = true;
    if (button) { button.disabled = true; button.textContent = "Analysiere …"; }
    if (summary) summary.textContent = "Freigegebene Medienordner werden analysiert …";
    try {
      const payload = await api.post("/api/storage/scan", { max_candidates: 40 });
      if (!current.active) return;
      view.scan(payload); jobs.syncLocks();
    }
    catch (error) { if (!current.active || isAbortError(error)) return; if (summary) summary.textContent = `Analyse fehlgeschlagen · ${error.message}`; }
    finally { if (!current.active) return; scanRunning = false; if (button) { button.disabled = false; button.textContent = "Große Inhalte analysieren"; } }
  }

  function closeMove() {
    planGeneration++;
    activeMove = null;
    const modal = find("storage-move-modal");
    if (modal) modal.hidden = true;
  }

  function renderMoveTargetNote() {
    const select = find("storage-move-target");
    const note = find("storage-move-target-note");
    if (!select || !note || !activeMove) return;
    const target = activeMove.plan.targets.find((item) => item.root === select.value);
    note.textContent = target
      ? `${target.path} · ${formatBytes(target.free_bytes)} frei · benötigt ca. ${formatBytes(target.required_bytes)}`
      : "Kein verfügbares Ziel ausgewählt.";
  }

  async function openMove(button) {
    const current = scope;
    if (!current?.active) return;
    const api = createStorageApi(current);
    const status = find("storage-cleanup-status");
    const payload = candidateData(button);
    const planId = ++planGeneration;
    button.disabled = true;
    if (status) status.textContent = "Verschiebeziel und vollständiger Inhalt werden sicher geprüft …";
    try {
      const plan = await api.post("/api/storage/move/plan", payload);
      if (!current.active || planId !== planGeneration) return;
      activeMove = { payload, plan };
      const modal = find("storage-move-modal");
      const select = find("storage-move-target");
      const blocked = find("storage-move-blocked");
      const confirm = find("storage-move-confirm");
      find("storage-move-name").textContent = plan.source_name || "Inhalt";
      find("storage-move-size").textContent = formatBytes(plan.size_bytes);
      find("storage-move-kind").textContent = plan.source_kind === "series" ? "GESAMTER SERIENORDNER" : "FILMDATEI";
      const eligible = (plan.targets || []).filter((item) => item.eligible);
      select.innerHTML = eligible.length
        ? eligible.map((item) => `<option value="${html(item.root)}">${html(item.label)} · ${formatBytes(item.free_bytes)} frei</option>`).join("")
        : '<option value="">Kein anderes Medien-Volume verfügbar</option>';
      select.disabled = !eligible.length;
      confirm.disabled = !eligible.length;
      blocked.innerHTML = (plan.targets || []).filter((item) => !item.eligible).map((item) => `<span>${html(item.label)}: ${html(item.reason || "nicht verfügbar")}</span>`).join("");
      renderMoveTargetNote();
      if (modal) modal.hidden = false;
      if (status) status.textContent = eligible.length ? `${plan.source_name} kann sicher verschoben werden.` : "Kein geeignetes anderes Medien-Volume gefunden.";
    } catch (error) { if (!current.active || isAbortError(error)) return;
      if (status) status.textContent = `Verschieben nicht möglich · ${error.message}`;
    } finally {
      if (!current.active) return;
      button.disabled = false;
    }
  }

  async function executeMove() {
    const current = scope;
    if (!current?.active) return;
    const api = createStorageApi(current);
    if (!activeMove) return;
    const select = find("storage-move-target");
    const destinationRoot = select?.value || "";
    const target = activeMove.plan.targets.find((item) => item.root === destinationRoot && item.eligible);
    if (!target) return;
    const name = activeMove.plan.source_name || "Inhalt";
    const kind = activeMove.plan.source_kind === "series" ? "der gesamte Serienordner" : "die Filmdatei";
    if (!window.confirm(`„${name}“ nach „${target.label}“ verschieben?\n\nEs wird ${kind} verschoben. Nach erfolgreichem Transfer wird die Quelle entfernt. Vorhandene Zieldaten werden niemals überschrieben.`)) return;
    const confirm = find("storage-move-confirm");
    const cancel = find("storage-move-cancel");
    const close = find("storage-move-close");
    const status = find("storage-cleanup-status");
    if (confirm) { confirm.disabled = true; confirm.textContent = "Verschiebe …"; }
    if (cancel) cancel.disabled = true;
    if (close) close.disabled = true;
    if (status) status.textContent = `${name} wird nach ${target.label} verschoben …`;
    try {
      const result = await api.post("/api/storage/move", {
        ...activeMove.payload,
        destination_root: destinationRoot,
        confirm: true,
      });
      if (!current.active) return;
      closeMove();
      if (result.job) jobs.accept(result.job);
      else if (status) status.textContent = `${result.name || name} verschoben · ${formatBytes(result.moved_bytes)} nach ${target.label}. Quelle wurde entfernt.`;
      if (current.active) await refreshStatus(false);
      if (current.active) await scanStorage();
    } catch (error) { if (!current.active || isAbortError(error)) return;
      if (status) status.textContent = `Verschieben abgebrochen · ${error.message}`;
    } finally {
      if (!current.active) return;
      if (confirm) { confirm.disabled = false; confirm.textContent = "Jetzt verschieben"; }
      if (cancel) cancel.disabled = false;
      if (close) close.disabled = false;
    }
  }

  async function cleanup(button) {
    const current = scope;
    if (!current?.active) return;
    const api = createStorageApi(current);
    const name = button.dataset.name || button.dataset.relativePath || "Inhalt";
    const size = Number(button.dataset.size) || 0;
    const status = find("storage-cleanup-status");
    if (!window.confirm(`„${name}“ (${formatBytes(size)}) dauerhaft löschen?\n\nDiese Bereinigung kann nicht rückgängig gemacht werden. Royal prüft den Treffer vor dem Löschen erneut.`)) return;
    button.disabled = true;
    if (status) status.textContent = `${name} wird erneut geprüft …`;
    try {
      const result = await api.post("/api/storage/cleanup", {
        root: button.dataset.root,
        relative_path: button.dataset.relativePath,
        token: button.dataset.token,
        expected_size: size,
        expires_at: Number(button.dataset.expiresAt) || 0,
        confirm: true,
      });
      if (!current.active) return;
      if (status) status.textContent = `${name} entfernt · ca. ${formatBytes(result.freed_bytes)} freigegeben.`;
      if (current.active) await refreshStatus(false);
      if (current.active) await scanStorage();
    } catch (error) { if (!current.active || isAbortError(error)) return;
      if (status) status.textContent = `Bereinigung abgebrochen · ${error.message}`;
      button.disabled = false;
    }
  }

  function bindView() {
    scope.listen(find("storage-refresh"), "click", () => refreshStatus(false));
    scope.listen(find("storage-scan"), "click", scanStorage);
    scope.listen(find("storage-location-form"), "submit", saveLocation);
    scope.listen(find("storage-location-mode"), "change", () => syncLocationMediaFields({ selectDefaults: true }));
    scope.listen(find("storage-location-cancel"), "click", resetLocationForm);
    scope.listen(find("storage-location-list"), "click", handleLocationAction);
    scope.listen(find("storage-large-content-list"), "click", (event) => {
      const move = event.target.closest("[data-storage-move]");
      if (move) { void openMove(move); return; }
      const cleanupButton = event.target.closest("[data-storage-cleanup]");
      if (cleanupButton) void cleanup(cleanupButton);
    });
    scope.listen(find("storage-move-close"), "click", closeMove);
    scope.listen(find("storage-move-cancel"), "click", closeMove);
    scope.listen(find("storage-move-confirm"), "click", executeMove);
    scope.listen(find("storage-move-target"), "change", renderMoveTargetNote);
    scope.listen(find("storage-move-modal"), "click", (event) => {
      if (event.target.id === "storage-move-modal") closeMove();
    });
    syncLocationMediaFields();
  }


  function stopView() {
    autopilot.unmount();
    jobs.unmount(); scope?.dispose(); scope = null; statusRequest = null;
    scanRunning = false; closeMove();
    find("storage-scan").disabled = false;
    find("storage-scan").textContent = "Große Inhalte analysieren";
    find("storage-location-save").disabled = false;
    find("storage-location-save").textContent = editingLocationId ? "Änderungen speichern" : "Speicherort hinzufügen";
    for (const id of ["storage-move-confirm", "storage-move-cancel", "storage-move-close"]) find(id).disabled = false;
    find("storage-move-confirm").textContent = "Jetzt verschieben";
    root.querySelectorAll("[data-storage-move], [data-storage-cleanup]").forEach(button => { button.disabled = false; });
  }
  function updateActivity() {
    const active = shell?.active && storageActive();
    if (!active) { if (scope) stopView(); return; }
    if (scope?.active) return;
    scope = createScope();
    bindView(); jobs.mount();
    autopilot.mount();
    void refreshStatus(false);
    scope.interval(() => { if (!document.hidden) void refreshStatus(true); }, POLL_MS);
    scope.listen(document, "visibilitychange", () => { if (!document.hidden) void refreshStatus(true); });
  }
  installStorageUi(root);
  const autopilot = createStorageAutopilot(root);
  return {
    mount() {
      if (shell?.active) return;
      shell = createScope();
      shell.listen(root.querySelector('[data-settings-target="settings-storage"]'), "click", (event) => {
        event.preventDefault(); activateStorage();
      });
      shell.listen(root.querySelector('[data-settings-open="settings-storage"]'), "click", activateStorage);

      const observer = new MutationObserver(updateActivity);
      observer.observe(find("settings-storage"), { attributes: true, attributeFilter: ["class", "hidden"] });
      shell.observe(observer);
      updateActivity();
    },
    refresh() { return Promise.all([refreshStatus(false), jobs.refresh()]); },
    unmount() { stopView(); shell?.dispose(); shell = null; },
  };
}
