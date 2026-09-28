import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { escapeHtml } from "../../shared/utils/escape-html.js";
import { createProviderMonitor } from "./provider-monitor.js";

/** Shared provider draft; backend acknowledgements replace it on load/save. */
export function createProviderSettings(settingsRoot, setupRoot, {
  client = api, onChange = () => {}, onApply = () => {}, onSetupStatus = () => {},
} = {}) {
  const data = { movies: [], series: [], anime: [], labels: {}, catalog: {}, languages: {},
    contentLanguages: new Set(), enabledMovies: new Set(), enabledSeries: new Set(), enabledAnime: new Set() };
  const active = new Set();
  const byId = id => [...active].map(root => root.querySelector(`#${id}`)).find(Boolean);
  let rows = createScope();
  let owner = createScope();
  let pending;
  let revision = 0;
  const monitor = createProviderMonitor(settingsRoot?.querySelector("#provider-monitor"), { client });
  function providerEnabledSet(mediaType) {
    if (mediaType === "movies") return data.enabledMovies;
    if (mediaType === "anime") return data.enabledAnime;
    return data.enabledSeries;
  }

  function providerLanguage(provider) {
    return String(data.catalog[provider]?.content_language || "").toLowerCase();
  }

  function providersForLanguage(language, mediaType) {
    return (data[mediaType] || []).filter(
      (provider) => providerLanguage(provider) === language,
    );
  }

  function renderContentLanguageSelectors() {
    const ids = ["content-language-options", "setup-content-language-options"];
    const selected = data.contentLanguages;
    for (const id of ids) {
      const container = byId(id);
      if (!container) continue;
      const context = id.startsWith("setup-") ? "setup" : "settings";
      container.innerHTML = Object.entries(data.languages).map(([language, label]) => {
        const active = selected.has(language);
        const providerCount = new Set([
          ...providersForLanguage(language, "movies"),
          ...providersForLanguage(language, "series"),
          ...providersForLanguage(language, "anime"),
        ]).size;
        return `
          <button class="content-language-card ${active ? "is-selected" : ""}" type="button"
            data-language="${escapeHtml(language)}" aria-pressed="${active}">
            <span class="content-language-code" translate="no">${escapeHtml(language.toUpperCase())}</span>
            <span class="content-language-copy">
              <strong translate="no">${escapeHtml(label)}</strong>
              <small>${providerCount} ${providerCount === 1 ? "Quelle" : "Quellen"}</small>
            </span>
            <span class="content-language-signal" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
          </button>
        `;
      }).join("");
      container.querySelectorAll(".content-language-card").forEach((button) => {
        rows.listen(button, "click", () => {
          revision++;
          const language = button.dataset.language;
          if (selected.has(language) && selected.size <= 1) {
            setProviderSelectionStatus(context, "Mindestens eine Inhaltssprache muss aktiv bleiben.", true);
            return;
          }
          if (selected.has(language)) {
            const remaining = new Set(selected);
            remaining.delete(language);
            const leavesMovies = data.movies.some(
              (provider) => remaining.has(providerLanguage(provider)),
            );
            const leavesSeries = data.series.some(
              (provider) => remaining.has(providerLanguage(provider)),
            );
            if (!leavesMovies || !leavesSeries) {
              setProviderSelectionStatus(
                context,
                "Die Auswahl benötigt mindestens eine Sprache mit Film- und Serienquellen.",
                true,
              );
              return;
            }
            selected.delete(language);
            for (const mediaType of ["movies", "series", "anime"]) {
              const enabled = providerEnabledSet(mediaType);
              providersForLanguage(language, mediaType).forEach((provider) => enabled.delete(provider));
            }
          } else {
            selected.add(language);
            for (const mediaType of ["movies", "series", "anime"]) {
              const enabled = providerEnabledSet(mediaType);
              providersForLanguage(language, mediaType).forEach((provider) => enabled.add(provider));
            }
          }
          const labels = [...selected].map((key) => data.languages[key] || key.toUpperCase());
          setProviderSelectionStatus(context, `Inhaltssprachen: ${labels.join(" + ")}.`);
          renderAllProviderBoards();
        });
      });
    }
    const labels = [...selected].map(
      (language) => data.languages[language] || language.toUpperCase(),
    );
    const summary = labels.length > 1
      ? `${labels.join(" + ")} · gemischter Katalog`
      : `${labels[0] || "Keine"} · fokussierter Katalog`;
    ["content-language-summary", "setup-content-language-summary"].forEach((id) => {
      const element = byId(id);
      if (element) element.textContent = summary;
    });
  }

  function providerMonogram(label) {
    const words = String(label || "").match(/[\p{L}\p{N}]+/gu) || [];
    return (words.length > 1
      ? words.slice(0, 2).map((word) => word[0]).join("")
      : String(words[0] || "?").slice(0, 2)
    ).toUpperCase();
  }

  function providerLogoUrl(meta) {
    const homepage = String(meta?.homepage || "").trim();
    if (!homepage) return "";
    return `https://www.google.com/s2/favicons?domain_url=${encodeURIComponent(homepage)}&sz=128`;
  }

  function providerListIds(mediaType) {
    if (mediaType === "movies") {
      return ["movie-provider-priority", "setup-movie-provider-priority"];
    }
    if (mediaType === "anime") {
      return ["anime-provider-priority", "setup-anime-provider-priority"];
    }
    return ["series-provider-priority", "setup-series-provider-priority"];
  }

  function setProviderSelectionStatus(context, message, error = false) {
    if (context === "setup") {
      onSetupStatus(message, error);
      return;
    }
    const status = byId("provider-selection-status");
    if (!status) return;
    status.textContent = message || "";
    status.classList.toggle("error", error);
  }

  function renderProviderList(list, mediaType) {
    const providers = data[mediaType] || [];
    const enabled = providerEnabledSet(mediaType);
    const isSetup = list.id.startsWith("setup-");
    const context = isSetup ? "setup" : "settings";
    const mediaLabel = {
      movies: "Filmquelle",
      series: "Serienquelle",
      anime: "Animequelle",
    }[mediaType];
    list.innerHTML = providers.map((provider, index) => {
      const meta = data.catalog[provider] || {};
      const label = data.labels[provider] || meta.label || provider;
      const languageActive = data.contentLanguages.has(providerLanguage(provider));
      const active = languageActive && enabled.has(provider);
      const logoUrl = providerLogoUrl(meta);
      const languageCode = String(meta.content_language || "").toUpperCase();
      const languageLabel = meta.language_label || languageCode;
      return `
        <li class="provider-source-card ${active ? "is-enabled" : "is-disabled"} ${languageActive ? "" : "is-language-muted"} ${mediaType === "series" ? "is-series" : ""}"
            data-provider="${escapeHtml(provider)}">
          <label class="provider-source-toggle">
            <input type="checkbox" ${active ? "checked" : ""}
              ${languageActive ? "" : "disabled"}
              aria-label="${escapeHtml(`${label} als ${mediaLabel} verwenden`)}">
            <span class="provider-logo-frame" aria-hidden="true">
              <span class="provider-logo-monogram">${escapeHtml(providerMonogram(label))}</span>
              ${logoUrl ? `<img class="provider-logo-image" src="${escapeHtml(logoUrl)}" alt="">` : ""}
            </span>
            <span class="provider-source-copy">
              <strong class="provider-name" translate="no">${escapeHtml(label)}</strong>
              <span class="provider-source-meta" translate="no">
                <em>${escapeHtml(languageCode)}</em>
                <small>${escapeHtml(languageLabel)}</small>
              </span>
            </span>
            <span class="provider-source-state" aria-hidden="true">
              <i>✓</i><small>${active ? "aktiv" : (languageActive ? "aus" : "Sprache aus")}</small>
            </span>
          </label>
          <span class="provider-source-order">
            <b title="Priorität">${String(index + 1).padStart(2, "0")}</b>
            <button class="provider-order-button" type="button" data-direction="-1"
              aria-label="${escapeHtml(`${label} nach oben`)}"
              ${index === 0 ? "disabled" : ""}>↑</button>
            <button class="provider-order-button" type="button" data-direction="1"
              aria-label="${escapeHtml(`${label} nach unten`)}"
              ${index === providers.length - 1 ? "disabled" : ""}>↓</button>
          </span>
        </li>
      `;
    }).join("");

    list.querySelectorAll(".provider-logo-image").forEach((image) => {
      rows.listen(image, "error", () => image.remove(), { once: true });
    });
    list.querySelectorAll('.provider-source-toggle input[type="checkbox"]').forEach((checkbox) => {
      rows.listen(checkbox, "change", () => {
        revision++;
        const provider = checkbox.closest(".provider-source-card").dataset.provider;
        if (mediaType !== "anime" && !checkbox.checked && enabled.size <= 1) {
          checkbox.checked = true;
          setProviderSelectionStatus(
            context,
            `Mindestens eine ${mediaType === "movies" ? "Filmquelle" : "Serienquelle"} muss aktiv bleiben.`,
            true,
          );
          return;
        }
        if (checkbox.checked) enabled.add(provider);
        else enabled.delete(provider);
        setProviderSelectionStatus(
          context,
          `${enabled.size} ${{
            movies: "Filmquellen",
            series: "Serienquellen",
            anime: "Animequellen",
          }[mediaType]} aktiv.`,
        );
        renderAllProviderBoards();
      });
    });
    list.querySelectorAll(".provider-order-button").forEach((button) => {
      rows.listen(button, "click", () => {
          revision++;
        const item = button.closest(".provider-source-card");
        const from = data[mediaType].indexOf(item.dataset.provider);
        const to = from + Number(button.dataset.direction);
        if (from < 0 || to < 0 || to >= data[mediaType].length) return;
        [data[mediaType][from], data[mediaType][to]] =
          [data[mediaType][to], data[mediaType][from]];
        renderAllProviderBoards();
      });
    });
  }

  function renderAllProviderBoards() {
    rows.dispose(); rows = createScope();
    renderContentLanguageSelectors();
    for (const mediaType of ["movies", "series", "anime"]) {
      for (const id of providerListIds(mediaType)) {
        const list = byId(id);
        if (list) renderProviderList(list, mediaType);
      }
      const enabledCount = providerEnabledSet(mediaType).size;
      const eligibleCount = (data[mediaType] || []).filter(
        (provider) => data.contentLanguages.has(providerLanguage(provider)),
      ).length;
      const summary = `${enabledCount} aktiv · ${eligibleCount} passend`;
      const ids = {
        movies: ["movie-provider-summary", "setup-movie-provider-summary"],
        series: ["series-provider-summary", "setup-series-provider-summary"],
        anime: ["anime-provider-summary", "setup-anime-provider-summary"],
      }[mediaType];
      ids.forEach((id) => {
        const element = byId(id);
        if (element) element.textContent = summary;
      });
    }
    onChange();
  }

  function applyProviderPriority(cfg) {
    data.movies = [...(cfg.movies || [])];
    data.series = [...(cfg.series || [])];
    data.anime = [...(cfg.anime || [])];
    data.labels = { ...(cfg.labels || {}) };
    data.catalog = { ...(cfg.catalog || {}) };
    data.languages = { ...(cfg.languages || {}) };
    data.enabledMovies = new Set(
      cfg.enabled_movies?.length ? cfg.enabled_movies : data.movies,
    );
    data.enabledSeries = new Set(
      cfg.enabled_series?.length ? cfg.enabled_series : data.series,
    );
    data.enabledAnime = new Set(
      Array.isArray(cfg.enabled_anime) ? cfg.enabled_anime : data.anime,
    );
    if (!Object.keys(data.languages).length) {
      for (const meta of Object.values(data.catalog)) {
        const language = String(meta.content_language || "").toLowerCase();
        if (language) data.languages[language] = meta.language_label || language.toUpperCase();
      }
    }
    const inferredLanguages = [
      ...data.enabledMovies,
      ...data.enabledSeries,
      ...data.enabledAnime,
    ].map(providerLanguage).filter(Boolean);
    data.contentLanguages = new Set(
      cfg.content_languages?.length
        ? cfg.content_languages
        : (inferredLanguages.length ? inferredLanguages : Object.keys(data.languages)),
    );
    for (const mediaType of ["movies", "series", "anime"]) {
      const enabled = providerEnabledSet(mediaType);
      [...enabled].forEach((provider) => {
        if (!data.contentLanguages.has(providerLanguage(provider))) enabled.delete(provider);
      });
    }
    onApply();
    renderAllProviderBoards();
  }


  const payload = () => ({ movies: data.movies, series: data.series, anime: data.anime,
    enabled_movies: [...data.enabledMovies], enabled_series: [...data.enabledSeries],
    enabled_anime: [...data.enabledAnime], content_languages: [...data.contentLanguages] });
  function initialize() {
    if (pending) return pending;
    const current = owner;
    const atRevision = revision;
    const request = client.get("/api/providers/config", { signal: current.signal })
      .then(value => { if (current.active && revision === atRevision) applyProviderPriority(value); })
      .finally(() => { if (pending === request) pending = null; });
    pending = request; return request;
  }
  function view(root) {
    return {
      mount() { if (active.has(root)) return; active.add(root); renderAllProviderBoards(); if (root === settingsRoot) monitor.mount(); },
      refresh: renderAllProviderBoards,
      unmount() { if (!active.delete(root)) return; if (root === settingsRoot) monitor.unmount(); renderAllProviderBoards(); },
    };
  }
  return {
    get: () => Object.freeze({ ...data }), language: providerLanguage, apply: applyProviderPriority,
    settings: view(settingsRoot), setup: view(setupRoot), initialize,
    async save({ signal } = {}) {
      const current = owner;
      const atRevision = revision;
      const value = await client.post("/api/providers/config", payload(), { signal: signal || current.signal });
      if (current.active && !signal?.aborted && revision === atRevision) applyProviderPriority(value);
      return value;
    },
    unmount() { owner.dispose(); rows.dispose(); monitor.unmount(); active.clear(); pending = null; },
    mount() { if (!owner.active) owner = createScope(); },
  };
}
