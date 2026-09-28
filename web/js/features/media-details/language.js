import { createScope } from "../../core/lifecycle.js";
import { createDialog } from "../../shared/components/dialog.js";
import { supportedProviderLanguages } from "../../shared/utils/provider-languages.js";

export function createMediaLanguage(document, { getProviders }) {
  let owner = null, modal = null, dialog = null, pending = null;
function normalizeUiContentLanguage(value) {
  const code = String(value || "").trim().replace("_", "-").toLowerCase().split("-", 1)[0];
  return code === "de" || code === "en" ? code : "";
}

function mediaContentLanguages(media = {}) {
  const languages = new Set();
  const add = (value) => {
    const normalized = normalizeUiContentLanguage(value);
    if (normalized) languages.add(normalized);
  };
  const providerLanguage = (provider) => {
    const key = String(provider || "").trim().toLowerCase();
    const metadata = getProviders().catalog?.[key];
    return supportedProviderLanguages(metadata).length === 1 ? metadata.content_language || "" : "";
  };

  add(media.content_language);
  for (const value of media.content_languages || []) add(value);
  if (media.provider) add(providerLanguage(media.provider));
  for (const source of [
    ...(Array.isArray(media.sources) ? media.sources : []),
    ...(Array.isArray(media.source_providers) ? media.source_providers : []),
  ]) {
    add(source?.content_language);
    if (source?.key) add(providerLanguage(source.key));
    else if (source?.provider) add(providerLanguage(source.provider));
  }
  return languages;
}

function mixedGermanEnglishContentEnabled() {
  return getProviders().contentLanguages.has("de")
    && getProviders().contentLanguages.has("en");
}

function mediaLanguageMarker(media) {
  if (!mixedGermanEnglishContentEnabled()) return null;
  const languages = mediaContentLanguages(media);
  const flags = [];
  const labels = [];
  if (languages.has("de")) {
    flags.push("🇩🇪");
    labels.push("Deutsch");
  }
  if (languages.has("en")) {
    flags.push("🇬🇧");
    labels.push("Englisch");
  }
  if (!flags.length) return null;
  return { text: flags.join(" "), label: labels.join(" und ") };
}

function appendMediaLanguageMarker(element, media) {
  const marker = mediaLanguageMarker(media);
  if (!element || !marker || element.dataset.languageMarked === "true") return;
  element.dataset.languageMarked = "true";
  element.textContent = `${element.textContent} · ${marker.text}`;
  const previousTitle = element.getAttribute("title") || "";
  element.setAttribute("title", [previousTitle, `Inhaltssprache: ${marker.label}`].filter(Boolean).join(" · "));
}

function movieDownloadLanguageOptions(movie = {}) {
  const grouped = new Map();
  const sources = Array.isArray(movie.source_providers) ? movie.source_providers : [];
  for (const source of sources) {
    const language = normalizeUiContentLanguage(source?.content_language);
    const hosterCount = Number(source?.hoster_count ?? source?.hosters?.length ?? 0);
    if (!language || hosterCount <= 0) continue;
    if (!grouped.has(language)) grouped.set(language, { language, providers: [], hosterCount: 0 });
    const option = grouped.get(language);
    option.hosterCount += hosterCount;
    if (source?.label && !option.providers.includes(source.label)) option.providers.push(source.label);
  }
  return grouped;
}

function createModal() {
  const modal = document.createElement("div");
  modal.id = "movie-language-choice";
  modal.className = "movie-language-choice";
  modal.hidden = true;
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "movie-language-title");
  modal.innerHTML = `
    <section class="movie-language-panel">
      <span class="movie-language-kicker">DOWNLOADSPRACHE</span>
      <h3 id="movie-language-title">Welche Sprache möchtest du?</h3>
      <p>Royal nutzt danach automatisch alle verfügbaren Anbieter-Fallbacks innerhalb dieser Sprache.</p>
      <div class="movie-language-options">
        <button class="movie-language-option" type="button" data-language="de"><b>🇩🇪</b><span><strong>Deutsch</strong><small></small></span></button>
        <button class="movie-language-option" type="button" data-language="en"><b>🇬🇧</b><span><strong>English</strong><small></small></span></button>
      </div>
      <button class="movie-language-cancel" type="button">Abbrechen</button>
    </section>
  `;
  document.body.appendChild(modal);
  return modal;
}


function ensureDialog() {
  if (modal) return;
  modal = createModal();
  dialog = createDialog(modal, {
    initialFocus: () => modal.querySelector('[data-language="en"]'),
    onClose() {
      modal.hidden = true;
      const resolve = pending; pending = null;
      resolve?.("");
    },
  });
}
function finish(value, restoreFocus = true) {
  const resolve = pending; pending = null;
  dialog?.close(restoreFocus);
  resolve?.(value);
}
function needsChoice(movie) {
  const options = movieDownloadLanguageOptions(movie);
  return mixedGermanEnglishContentEnabled() && options.has("de") && options.has("en");
}
function choose(movie, trigger = document.activeElement) {
  if (!owner?.active || !needsChoice(movie)) return Promise.resolve(null);
  finish("", false);
  ensureDialog();
  const options = movieDownloadLanguageOptions(movie);
  for (const language of ["de", "en"]) {
    const data = options.get(language);
    const button = modal.querySelector(`[data-language="${language}"]`);
    const providerText = data.providers.slice(0, 3).join(" · ");
    const extraProviders = Math.max(0, data.providers.length - 3);
    button.querySelector("small").textContent = [
      `${data.hosterCount} Hoster`, providerText, extraProviders ? `+${extraProviders} weitere` : "",
    ].filter(Boolean).join(" · ");
  }
  modal.hidden = false;
  const scope = dialog.open(trigger);
  scope.listen(modal, "click", event => {
    const option = event.target.closest("[data-language]");
    if (option) finish(option.dataset.language);
    else if (event.target.closest(".movie-language-cancel")) finish("");
  });
  return new Promise(resolve => { pending = resolve; });
}
return {
  normalize: normalizeUiContentLanguage, languages: mediaContentLanguages,
  mark: appendMediaLanguageMarker, options: movieDownloadLanguageOptions, needsChoice, choose,
  close: () => finish("", false),
  mount() {
    if (owner?.active) return;
    owner = createScope();
    owner.listen(document, "royal:navigate", () => finish("", false));
  },
  unmount() { finish("", false); owner?.dispose(); owner = null; modal?.remove(); modal = null; dialog = null; },
};
}
