const i18n = (() => {
  const SOURCE_LANGUAGE = "de";
  const FALLBACK_LANGUAGES = {
    de: "Deutsch",
    en: "English",
    es: "Español",
    fr: "Français",
    it: "Italiano",
    nl: "Nederlands",
    pl: "Polski",
    pt: "Português",
    tr: "Türkçe",
    uk: "Українська",
  };
  const ATTRIBUTES = ["placeholder", "title", "aria-label"];
  const SKIP_SELECTOR = [
    "script", "style", "code", "pre", "textarea",
    "[translate='no']", "[data-i18n-ignore]",
    ".log-line", ".result-card-title", ".queue-item-title",
    ".queue-item-route", ".subscription-name", ".library-card-title",
    ".dir-item", ".provider-name",
  ].join(",");

  let language = SOURCE_LANGUAGE;
  let languages = { ...FALLBACK_LANGUAGES };
  let configured = false;
  let initialized = false;
  let observer = null;
  let browserTranslator = null;
  let browserTranslatorLanguage = "";
  let generation = 0;
  let pendingTimer = null;
  let pendingEntries = new Set();
  let lastEngine = "source";

  const textEntries = new WeakMap();
  const attributeEntries = new WeakMap();
  const allEntries = new Set();
  const translations = new Map();

  function normalizeLanguage(value) {
    const code = String(value || "").trim().replaceAll("_", "-").toLowerCase();
    if (languages[code]) return code;
    const base = code.split("-", 1)[0];
    return languages[base] ? base : SOURCE_LANGUAGE;
  }

  function locale() {
    return ({
      de: "de-DE", en: "en-US", es: "es-ES", fr: "fr-FR", it: "it-IT",
      nl: "nl-NL", pl: "pl-PL", pt: "pt-PT", tr: "tr-TR", uk: "uk-UA",
    })[language] || language;
  }

  function browserDefaultLanguage() {
    for (const candidate of navigator.languages || [navigator.language]) {
      const normalized = normalizeLanguage(candidate);
      if (normalized !== SOURCE_LANGUAGE || String(candidate || "").toLowerCase().startsWith("de")) {
        return normalized;
      }
    }
    return SOURCE_LANGUAGE;
  }

  function sourceParts(value) {
    const raw = String(value ?? "");
    const match = raw.match(/^(\s*)([\s\S]*?)(\s*)$/);
    return {
      prefix: match?.[1] || "",
      source: match?.[2] || "",
      suffix: match?.[3] || "",
    };
  }

  function isUsefulSource(value) {
    const text = String(value || "").trim();
    if (!text || text.length > 600 || !/\p{L}/u.test(text)) return false;
    if (/(?:https?:\/\/|wss?:\/\/)/i.test(text)) return false;
    if (/\/[A-Za-z0-9._-]+\/[A-Za-z0-9._/-]+/.test(text)) return false;
    if (/[A-Za-z]:\\/.test(text)) return false;
    if (/^[A-Z0-9_.:@/+*-]{18,}$/.test(text)) return false;
    return true;
  }

  function shouldSkip(element) {
    return !element || element.closest(SKIP_SELECTOR) !== null;
  }

  function updateTextEntry(node) {
    if (!node?.parentElement || shouldSkip(node.parentElement)) return null;
    const parts = sourceParts(node.nodeValue);
    if (!isUsefulSource(parts.source)) return null;
    let entry = textEntries.get(node);
    if (entry && node.nodeValue === entry.rendered) return entry;
    if (!entry) {
      entry = { kind: "text", node, ...parts, rendered: node.nodeValue };
      textEntries.set(node, entry);
      allEntries.add(entry);
    } else {
      Object.assign(entry, parts);
      entry.rendered = node.nodeValue;
    }
    return entry;
  }

  function updateAttributeEntry(element, attribute) {
    if (shouldSkip(element) || !element.hasAttribute(attribute)) return null;
    const parts = sourceParts(element.getAttribute(attribute));
    if (!isUsefulSource(parts.source)) return null;
    let entries = attributeEntries.get(element);
    if (!entries) {
      entries = new Map();
      attributeEntries.set(element, entries);
    }
    let entry = entries.get(attribute);
    if (entry && element.getAttribute(attribute) === entry.rendered) return entry;
    if (!entry) {
      entry = {
        kind: "attribute", element, attribute, ...parts,
        rendered: element.getAttribute(attribute),
      };
      entries.set(attribute, entry);
      allEntries.add(entry);
    } else {
      Object.assign(entry, parts);
      entry.rendered = element.getAttribute(attribute);
    }
    return entry;
  }

  function collect(root = document.documentElement) {
    const collected = new Set();
    if (root.nodeType === Node.TEXT_NODE) {
      const entry = updateTextEntry(root);
      if (entry) collected.add(entry);
      return collected;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return collected;
    const base = root.nodeType === Node.DOCUMENT_NODE ? root.documentElement : root;
    if (!base || shouldSkip(base)) return collected;

    const walker = document.createTreeWalker(base, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const entry = updateTextEntry(node);
      if (entry) collected.add(entry);
      node = walker.nextNode();
    }

    const elements = [base, ...base.querySelectorAll("*")];
    for (const element of elements) {
      for (const attribute of ATTRIBUTES) {
        const entry = updateAttributeEntry(element, attribute);
        if (entry) collected.add(entry);
      }
    }
    return collected;
  }

  function renderEntry(entry, translated) {
    if (!entry) return;
    const value = `${entry.prefix}${translated || entry.source}${entry.suffix}`;
    entry.rendered = value;
    if (entry.kind === "text" && entry.node.isConnected) {
      entry.node.nodeValue = value;
    } else if (entry.kind === "attribute" && entry.element.isConnected) {
      entry.element.setAttribute(entry.attribute, value);
    }
  }

  function restoreGerman() {
    for (const entry of [...allEntries]) {
      const connected = entry.kind === "text" ? entry.node.isConnected : entry.element.isConnected;
      if (!connected) {
        allEntries.delete(entry);
        continue;
      }
      renderEntry(entry, entry.source);
    }
  }

  function translationCache(target) {
    if (!translations.has(target)) translations.set(target, new Map());
    return translations.get(target);
  }

  async function getBrowserTranslator(target, userInitiated, onProgress) {
    if (
      !window.isSecureContext
      || !("Translator" in window)
      || target === SOURCE_LANGUAGE
    ) return null;
    if (browserTranslator && browserTranslatorLanguage === target) return browserTranslator;
    if (browserTranslator?.destroy) browserTranslator.destroy();
    browserTranslator = null;
    browserTranslatorLanguage = "";
    try {
      const options = { sourceLanguage: SOURCE_LANGUAGE, targetLanguage: target };
      const availability = await window.Translator.availability(options);
      if (availability === "unavailable") return null;
      if (availability !== "available" && !userInitiated) return null;
      browserTranslator = await window.Translator.create({
        ...options,
        monitor(monitor) {
          monitor.addEventListener("downloadprogress", (event) => {
            onProgress?.(Math.round(Number(event.loaded || 0) * 100));
          });
        },
      });
      browserTranslatorLanguage = target;
      return browserTranslator;
    } catch (error) {
      console.info("Lokaler Browser-Translator nicht verfügbar:", error);
      browserTranslator = null;
      browserTranslatorLanguage = "";
      return null;
    }
  }

  async function mapWithConcurrency(values, limit, worker) {
    const results = new Array(values.length);
    let cursor = 0;
    async function run() {
      while (cursor < values.length) {
        const index = cursor++;
        results[index] = await worker(values[index], index);
      }
    }
    await Promise.all(Array.from({ length: Math.min(limit, values.length) }, run));
    return results;
  }

  async function serverTranslate(target, values) {
    const translated = [];
    for (let index = 0; index < values.length; index += 80) {
      const chunk = values.slice(index, index + 80);
      const response = await api.uiTranslate(target, chunk);
      translated.push(...(response.translations || chunk));
      lastEngine = response.engine || "server";
    }
    return translated;
  }

  async function resolveTranslations(target, sources, { userInitiated = false } = {}) {
    const cache = translationCache(target);
    const unique = [...new Set(sources)].filter((source) => !cache.has(source));
    if (!unique.length) return cache;

    const translator = await getBrowserTranslator(
      target,
      userInitiated,
      (progress) => setStatus(`Sprachmodell wird geladen … ${progress}%`),
    );
    let translated;
    if (translator) {
      lastEngine = "browser";
      translated = await mapWithConcurrency(unique, 4, async (source) => {
        try {
          return await translator.translate(source);
        } catch (error) {
          return "";
        }
      });
      const failedIndexes = translated
        .map((value, index) => value ? -1 : index)
        .filter((index) => index >= 0);
      if (failedIndexes.length) {
        try {
          const fallback = await serverTranslate(
            target,
            failedIndexes.map((index) => unique[index]),
          );
          failedIndexes.forEach((sourceIndex, fallbackIndex) => {
            translated[sourceIndex] = fallback[fallbackIndex];
          });
        } catch (error) {
          console.warn("Server-Übersetzer nicht verfügbar:", error);
        }
      }
    } else {
      try {
        translated = await serverTranslate(target, unique);
      } catch (error) {
        console.warn("Automatische Übersetzung nicht verfügbar:", error);
        translated = unique;
        lastEngine = "fallback";
      }
    }
    unique.forEach((source, index) => cache.set(source, translated[index] || source));
    return cache;
  }

  async function translateEntries(entries, options = {}) {
    const activeGeneration = generation;
    const connected = [...entries].filter((entry) => (
      entry.kind === "text" ? entry.node.isConnected : entry.element.isConnected
    ));
    if (!connected.length) return;
    if (language === SOURCE_LANGUAGE) {
      connected.forEach((entry) => renderEntry(entry, entry.source));
      return;
    }
    const cache = await resolveTranslations(
      language,
      connected.map((entry) => entry.source),
      options,
    );
    if (activeGeneration !== generation) return;
    connected.forEach((entry) => renderEntry(entry, cache.get(entry.source) || entry.source));
  }

  function queueTranslation(entries) {
    for (const entry of entries) pendingEntries.add(entry);
    if (pendingTimer) clearTimeout(pendingTimer);
    pendingTimer = setTimeout(async () => {
      const batch = pendingEntries;
      pendingEntries = new Set();
      pendingTimer = null;
      await translateEntries(batch);
    }, 60);
  }

  function observe() {
    if (observer) observer.disconnect();
    observer = new MutationObserver((mutations) => {
      const changed = new Set();
      for (const mutation of mutations) {
        if (mutation.type === "characterData") {
          const known = textEntries.get(mutation.target);
          if (known && mutation.target.nodeValue === known.rendered) continue;
          const entry = updateTextEntry(mutation.target);
          if (entry) changed.add(entry);
        } else if (mutation.type === "attributes") {
          const known = attributeEntries.get(mutation.target)?.get(mutation.attributeName);
          if (
            known
            && mutation.target.getAttribute(mutation.attributeName) === known.rendered
          ) continue;
          const entry = updateAttributeEntry(mutation.target, mutation.attributeName);
          if (entry) changed.add(entry);
        } else {
          for (const node of mutation.addedNodes) {
            for (const entry of collect(node)) changed.add(entry);
          }
        }
      }
      if (changed.size) queueTranslation(changed);
    });
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRIBUTES,
    });
  }

  function syncSelectors() {
    for (const id of ["ui-language", "setup-ui-language"]) {
      const select = document.getElementById(id);
      if (select && select.value !== language) select.value = language;
    }
  }

  function setStatus(message, error = false) {
    const status = document.getElementById("ui-language-status");
    if (!status) return;
    status.textContent = message || "";
    status.classList.toggle("error", error);
  }

  async function changeLanguage(value, {
    persist = false,
    userInitiated = false,
  } = {}) {
    const target = normalizeLanguage(value);
    generation += 1;
    language = target;
    document.documentElement.lang = target;
    document.documentElement.dir = "ltr";
    syncSelectors();
    restoreGerman();
    const entries = collect(document.documentElement);
    if (target === SOURCE_LANGUAGE) {
      lastEngine = "source";
      setStatus("Deutsch · Ausgangssprache");
    } else {
      setStatus("Oberfläche wird automatisch übersetzt …");
      await translateEntries(entries, { userInitiated });
      const engineLabel = lastEngine === "browser"
        ? "lokal im Browser"
        : lastEngine === "fallback" ? "deutscher Fallback" : "serverseitig";
      setStatus(`${languages[target]} · automatisch ${engineLabel}`);
    }
    if (persist) {
      const response = await api.uiConfigSet(target);
      configured = !!response.configured;
    }
    return target;
  }

  async function initialize() {
    if (initialized) return { language, languages, configured };
    let response = null;
    try {
      response = await api.uiConfigGet();
      languages = { ...FALLBACK_LANGUAGES, ...(response.languages || {}) };
      configured = !!response.configured;
      language = normalizeLanguage(response.language);
    } catch (error) {
      console.warn("Sprachkonfiguration nicht verfügbar:", error);
    }
    collect(document.documentElement);
    observe();
    initialized = true;
    await changeLanguage(language);
    return { language, languages, configured };
  }

  return {
    initialize,
    changeLanguage,
    browserDefaultLanguage,
    locale,
    get language() { return language; },
    get languages() { return { ...languages }; },
    get configured() { return configured; },
  };
})();

window.i18n = i18n;
