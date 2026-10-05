import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { escapeHtml as escape } from "../../shared/utils/escape-html.js";

/** A private draft until one backend acknowledgement; readiness is awaited before closing. */
export function createLanguageSetup(dialog, { client = api, language, changeLanguage, providers, onReady = async () => {}, onComplete = () => {} }) {
  const by = name => dialog.querySelector(`[data-language-setup="${name}"]`);
  let owner, rows, snapshot, draft, step = 0, busy = false, committed = false, ready = false, trigger;
  const labels = () => snapshot?.providers.languages || {};
  const names = values => values.map(value => labels()[value] || value.toUpperCase()).join(" + ");
  const text = (de, en) => draft?.uiLanguage === "en" ? en : de;
  const selectedNames = () => names([...draft.contentLanguages]);
  const subscriptionLabel = entry => draft.subscriptions.has(entry.base_slug)
    ? `${escape(names(entry.content_languages))} <span aria-hidden="true">→</span> <b>${escape(selectedNames())}</b>`
    : `${escape(names(entry.content_languages))} · ${text("bleibt erhalten", "kept")}`;
  function progress(index, message) {
    by("busy-copy").textContent = message;
    by("busy").querySelectorAll("li").forEach((item, i) => {
      item.classList.toggle("is-current", i === index);
      item.classList.toggle("is-done", i < index);
    });
  }
  function summary() {
    by("selection").textContent = `${snapshot.ui_languages[draft.uiLanguage]} / ${selectedNames()}`;
    const changed = draft.subscriptions.size;
    by("subscription-summary").textContent = text(
      `${changed} von ${snapshot.subscriptions.length} Serien übernehmen die neue Inhaltswahl.`,
      `${changed} of ${snapshot.subscriptions.length} series will use the new content languages.`);
  }
  function render() {
    rows?.dispose(); rows = createScope();
    dialog.dataset.step = String(step);
    by("title").textContent = text("Dein Royal. Deine Sprache.", "Your Royal. Your language.");
    by("intro").textContent = text("Eine Oberfläche, passende Inhalte und Abos, die mitdenken.", "An interface, content and subscriptions that work together.");
    const steps = [text("Oberfläche", "Interface"), text("Inhalte", "Content"), text("Meine Liste", "My list")];
    by("steps").innerHTML = steps.map((name, index) => `<li class="${index === step ? "is-current" : index < step ? "is-done" : ""}" ${index === step ? 'aria-current="step"' : ""}><span>${index < step ? "✓" : index + 1}</span>${name}</li>`).join("");
    by("cancel").textContent = text("Abbrechen", "Cancel");
    by("back").textContent = text("Zurück", "Back");
    by("back").hidden = step === 0;
    by("next").textContent = step === 2 ? text("Profil übernehmen", "Apply profile") : text("Weiter", "Continue");
    const options = Object.entries(snapshot.ui_languages).map(([code, name]) => `<option value="${escape(code)}" ${code === draft.uiLanguage ? "selected" : ""}>${escape(name)}</option>`).join("");
    const panels = [
      `<div class="language-studio-panel"><div class="language-studio-lead"><span class="language-studio-number">01</span><h3>${text("Wie soll Royal mit dir sprechen?", "How should Royal speak to you?")}</h3><p>${text("Wähle deine Oberflächensprache. Die Inhaltssprache entscheidest du im nächsten Schritt.", "Choose your interface language. You will choose content languages in the next step.")}</p></div><label class="language-studio-field" for="language-setup-interface">${text("Oberflächensprache", "Interface language")}<select id="language-setup-interface">${options}</select></label><div class="language-studio-preview"><span class="language-studio-preview-brand">Royal</span><span class="language-studio-preview-nav">${text("Filme", "Movies")}<b>${text("Serien", "Series")}</b>${text("Meine Liste", "My list")}</span><strong>${text("Dein nächster Serienabend.", "Your next series night.")}</strong><p>${text("Alles, was du sehen möchtest. An einem Ort.", "Everything you want to watch. In one place.")}</p><div class="language-studio-preview-tiles" aria-hidden="true"><i></i><i></i><i></i><i></i></div></div></div>`,
      `<div class="language-studio-panel"><div class="language-studio-lead"><span class="language-studio-number">02</span><h3>${text("Was möchtest du hören?", "What would you like to hear?")}</h3><p>${text("Die Sprache der Filme und Serien ist unabhängig von deiner Oberfläche. Du kannst mehrere auswählen.", "Movie and series audio is independent of your interface. You can choose more than one.")}</p></div><div class="language-studio-languages" role="group" aria-label="${text("Inhaltssprachen", "Content languages")}">${Object.entries(labels()).map(([code, name]) => `<button type="button" class="language-studio-choice ${draft.contentLanguages.has(code) ? "is-selected" : ""}" data-content-language="${escape(code)}" aria-pressed="${draft.contentLanguages.has(code)}"><span>${escape(code.toUpperCase())}</span><strong>${escape(name)}</strong><i aria-hidden="true">✓</i></button>`).join("")}</div><div class="language-studio-assist"><span aria-hidden="true">⇄</span><div><strong>${text("Passende Quellen? Erledigt.", "Matching sources? Taken care of.")}</strong><p>${text("Royal aktiviert passende Quellen und übernimmt deine Reihenfolge. Ohne passende Sprachspur wartet eine Folge auf ihren Release.", "Royal enables matching sources and keeps your priority order. Episodes wait until matching audio is available.")}</p></div></div></div>`,
      `<div class="language-studio-panel"><div class="language-studio-lead"><span class="language-studio-number">03</span><h3>${text("Sollen deine Serien mitwechseln?", "Should your series switch too?")}</h3><p>${text("Markierte Serien verwenden künftig die neue Inhaltswahl. Andere behalten ihre bisherige Sprache. Vorhandene Dateien und geplante Downloads bleiben erhalten.", "Selected series will use the new content languages for future downloads. Others keep their current languages. Existing files and queued downloads are preserved.")}</p></div>${snapshot.subscriptions.length ? `<div class="language-studio-list-actions"><button type="button" data-subscription-selection="all">${text("Alle umstellen", "Switch all")}</button><button type="button" data-subscription-selection="none">${text("Bisherige Sprachen behalten", "Keep current languages")}</button></div><div class="language-studio-subscriptions">${snapshot.subscriptions.map(entry => `<label class="language-studio-subscription"><input type="checkbox" data-subscription="${escape(entry.base_slug)}" ${draft.subscriptions.has(entry.base_slug) ? "checked" : ""}><span><strong>${escape(entry.title)}</strong><small>${subscriptionLabel(entry)}</small></span><i aria-hidden="true">✓</i></label>`).join("")}</div>` : `<div class="language-studio-empty"><span aria-hidden="true">♡</span><strong>${text("Deine Liste ist noch leer.", "Your list is empty.")}</strong><p>${text("Neue Serien verwenden automatisch deine Inhaltswahl.", "New series will automatically use your content languages.")}</p></div>`}<div class="language-studio-review"><span>${text("Dein neues Profil", "Your new profile")}</span><strong>${escape(snapshot.ui_languages[draft.uiLanguage])} <small>/</small> ${escape(selectedNames())}</strong></div></div>`
    ];
    by("content").innerHTML = panels[step];
    rows.listen(by("content"), "change", event => {
      if (event.target.id === "language-setup-interface") {
        draft.uiLanguage = event.target.value; render();
        dialog.querySelector("#language-setup-interface").focus();
      } else if (event.target.dataset.subscription) {
        if (event.target.checked) draft.subscriptions.add(event.target.dataset.subscription);
        else draft.subscriptions.delete(event.target.dataset.subscription);
        const entry = snapshot.subscriptions.find(item => item.base_slug === event.target.dataset.subscription);
        event.target.closest("label").querySelector("small").innerHTML = subscriptionLabel(entry);
        summary();
      }
    });
    rows.listen(by("content"), "click", event => {
      const choice = event.target.closest("[data-content-language]");
      if (choice) {
        const code = choice.dataset.contentLanguage;
        if (draft.contentLanguages.has(code)) draft.contentLanguages.delete(code);
        else draft.contentLanguages.add(code);
        choice.classList.toggle("is-selected", draft.contentLanguages.has(code));
        choice.setAttribute("aria-pressed", String(draft.contentLanguages.has(code)));
        by("error").textContent = ""; summary();
      }
      const selection = event.target.closest("[data-subscription-selection]");
      if (selection) {
        draft.subscriptions = new Set(selection.dataset.subscriptionSelection === "all" ? snapshot.subscriptions.map(entry => entry.base_slug) : []);
        render();
      }
    });
    by("busy").querySelector("p").textContent = text("Royal macht alles bereit.", "Royal is getting everything ready.");
    by("busy").querySelectorAll("li").forEach((item, index) => { item.textContent = [text("Sprachprofil speichern", "Save language profile"), text("Quellen & Serien vorbereiten", "Prepare sources & series"), text("Oberfläche umstellen", "Prepare interface")][index]; });
    summary();
  }
  function close() {
    if ((busy && snapshot) || (committed && !ready)) return;
    dialog.close(); owner?.dispose(); rows?.dispose();
    trigger?.focus();
  }
  async function apply() {
    if (busy) return;
    busy = true;
    const current = owner;
    by("content").hidden = true; by("steps").hidden = true; by("busy").hidden = false;
    by("footer").hidden = true; by("error").textContent = "";
    dialog.setAttribute("aria-busy", "true");
    try {
      progress(0, text("Dein Sprachprofil wird gespeichert …", "Saving your language profile …"));
      if (!committed) {
        const result = await client.post("/api/providers/language-setup", {
          revision: snapshot.revision, ui_language: draft.uiLanguage,
          content_languages: [...draft.contentLanguages], update_subscriptions: [...draft.subscriptions],
        }, { signal: current.signal });
        if (!current.active) return;
        committed = true; providers.apply(result.providers);
      }
      progress(1, text("Quellen und Serien werden vorbereitet …", "Preparing sources and subscriptions …"));
      await onReady({ signal: current.signal });
      if (!current.active) return;
      progress(2, text("Deine Oberfläche wird umgestellt …", "Preparing your interface …"));
      await changeLanguage(draft.uiLanguage);
      if (!current.active) return;
      progress(3, text("Alles bereit.", "Everything is ready."));
      onComplete(); ready = true; busy = false; close();
    } catch (error) {
      if (!current.active) return;
      by("error").textContent = committed
        ? text(`Profil gespeichert. Die Vorbereitung ist noch nicht fertig: ${error.message}`, `Profile saved. Preparation is not finished: ${error.message}`)
        : error.message;
      by("footer").hidden = false; by("cancel").disabled = committed;
      by("back").hidden = true;
      by("next").textContent = text("Erneut versuchen", "Try again");
      by("next").focus();
    } finally { if (current.active) { busy = false; dialog.removeAttribute("aria-busy"); } }
  }
  async function open({ uiLanguage = language(), contentLanguages } = {}) {
    if (dialog.open) return;
    trigger = dialog.ownerDocument.activeElement;
    owner?.dispose(); owner = createScope(); committed = false; ready = false; busy = false; step = 0; snapshot = null; draft = null;
    by("next").hidden = false;
    const current = owner;
    by("content").hidden = true; by("busy").hidden = false; by("steps").hidden = true;
    by("footer").hidden = true; by("error").textContent = ""; by("cancel").disabled = false;
    by("title").textContent = "Dein Royal. Deine Sprache.";
    by("busy-copy").textContent = "Dein Sprachprofil wird geladen …";
    dialog.showModal();
    current.listen(dialog, "cancel", event => { event.preventDefault(); close(); });
    current.listen(by("cancel"), "click", close);
    current.listen(by("back"), "click", () => { step--; render(); by("content").focus(); });
    current.listen(by("next"), "click", () => {
      if (!snapshot) { void load(); return; }
      if (committed || by("busy").hidden === false && snapshot) { void apply(); return; }
      if (step === 1) {
        const selected = [...draft.contentLanguages];
        const supports = kind => snapshot.providers[kind].some(provider =>
          (snapshot.providers.catalog[provider]?.content_languages || [snapshot.providers.catalog[provider]?.content_language]).some(code => selected.includes(code)));
        if (!selected.length || !supports("movies") || !supports("series")) {
          by("error").textContent = text("Wähle mindestens eine Sprache mit Film- und Serienquellen.", "Choose at least one language with movie and series sources."); return;
        }
      }
      if (step === 2) void apply();
      else { step++; render(); by("content").focus(); }
    });
    async function load() {
      if (busy) return;
      busy = true;
      by("content").hidden = true; by("busy").hidden = false; by("footer").hidden = true;
      by("error").textContent = "";
      try {
        snapshot = await client.get("/api/providers/language-setup", { signal: current.signal, timeoutMs: 10000 });
        if (!current.active) return;
        draft = { uiLanguage, contentLanguages: new Set(contentLanguages || snapshot.providers.content_languages), subscriptions: new Set() };
        by("content").hidden = false; by("steps").hidden = false; by("busy").hidden = true; by("footer").hidden = false;
        render(); by("content").focus();
      } catch (error) {
        if (!current.active) return;
        snapshot = null; draft = null;
        by("busy").hidden = true;
        by("error").textContent = uiLanguage === "en"
          ? "Royal cannot load your language profile right now. Please try again. Nothing has changed."
          : "Royal kann dein Sprachprofil gerade nicht laden. Bitte erneut versuchen. Es wurde nichts geändert.";
        by("footer").hidden = false; by("next").hidden = false; by("back").hidden = true;
        by("next").textContent = uiLanguage === "en" ? "Try again" : "Erneut versuchen";
        by("next").focus();
      } finally { if (current.active) busy = false; }
    }
    await load();
  }
  return { open, dispose() { busy = false; committed = false; close(); owner?.dispose(); rows?.dispose(); } };
}
