/* Optional, provider-neutral ranking over Royal's existing discovery candidates. */

function aiFormConfig() {
  return {
    enabled: Boolean(document.getElementById("ai-enabled")?.checked),
    url: document.getElementById("ai-url")?.value.trim() || "http://127.0.0.1:11434",
    model: document.getElementById("ai-model")?.value.trim() || "llama3.2:3b",
    timeout_seconds: Math.max(
      30,
      Math.min(300, Number(document.getElementById("ai-timeout")?.value) || 180),
    ),
  };
}

function syncAiSettingsState() {
  const enabled = Boolean(document.getElementById("ai-enabled")?.checked);
  ["ai-url", "ai-model", "ai-test"].forEach((id) => {
    const element = document.getElementById(id);
    if (element) element.disabled = !enabled;
  });
  const status = document.getElementById("ai-status");
  if (!status) return;
  const badge = document.getElementById("ai-provider-badge");
  const privacy = document.getElementById("ai-privacy-note");
  if (badge) badge.textContent = "LOKAL";
  if (privacy) privacy.textContent = "Royal Reflex verarbeitet kompakte Katalogmetadaten und dein Geschmacksprofil ausschließlich lokal über Ollama.";
  if (enabled !== state.ai.enabled) {
    status.textContent = enabled
      ? "Aktivierung noch speichern."
      : "Deaktivierung noch speichern.";
  } else if (enabled) {
    status.textContent = `Aktiviert · ${state.ai.model || "Royal Intelligence"} kuratiert die Discovery.`;
  } else {
    status.textContent = "Deaktiviert · Royal nutzt das klassische Ranking.";
  }
}

function applyAiConfig(config = {}) {
  state.ai.enabled = Boolean(config.enabled);
  state.ai.configured = Boolean(config.configured);
  state.ai.model = String(config.model || "");
  state.ai.moduleAvailable = Boolean(config.module_available);
  const enabled = document.getElementById("ai-enabled");
  const url = document.getElementById("ai-url");
  const model = document.getElementById("ai-model");
  const timeout = document.getElementById("ai-timeout");
  if (enabled) enabled.checked = state.ai.enabled;
  if (url) url.value = config.url || "http://127.0.0.1:11434";
  if (model) model.value = config.model || "llama3.2:3b";
  if (timeout) timeout.value = String(config.timeout_seconds || 180);
  syncAiSettingsState();
  if (state.ai.enabled && state.ai.moduleAvailable) {
    setAiDiscoveryState("waiting", "Royal Intelligence wartet auf die Titel der Startseite.");
  } else {
    const rail = document.getElementById("home-ai-rail");
    if (rail) rail.hidden = true;
  }
}

async function testAiConnection() {
  const button = document.getElementById("ai-test");
  const status = document.getElementById("ai-status");
  if (!button || !status) return;
  button.disabled = true;
  status.textContent = "Provider wird geprüft …";
  try {
    const result = await api.aiTest(aiFormConfig());
    const models = Array.isArray(result.models) ? result.models : [];
    const datalist = document.getElementById("ai-models");
    if (datalist) {
      datalist.replaceChildren(...models.map((name) => {
        const option = document.createElement("option");
        option.value = name;
        return option;
      }));
    }
    status.textContent = result.model_available
      ? `Verbunden · ${models.length} Modell(e) verfügbar.`
      : `Verbunden · Modell noch nicht geladen (${models.length} verfügbar).`;
    if (Boolean(document.getElementById("ai-enabled")?.checked) !== state.ai.enabled) {
      status.textContent += " · Aktivierung noch speichern.";
    }
  } catch (error) {
    status.textContent = `Nicht erreichbar · ${error.message}`;
  } finally {
    button.disabled = !document.getElementById("ai-enabled")?.checked;
  }
}

async function saveAiSettings() {
  const config = await api.aiConfigSet(aiFormConfig());
  applyAiConfig(config);
  state.ai.lastFingerprint = "";
  if (!config.enabled) {
    document.getElementById("home-ai-rail").hidden = true;
    state.ai.recommendations = [];
  } else if (typeof window.refreshAiDiscovery === "function") {
    void window.refreshAiDiscovery(true);
  }
  return config;
}

function aiDiscoveryCandidates() {
  if (typeof homeAllEntries !== "function") return [];
  const seen = new Set();
  return homeAllEntries().filter((entry) => {
    const key = homeEntryKey(entry);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return mediaJellyfinStatus(homeEntryMedia(entry)) !== "owned";
  }).slice(0, 24).map((entry) => {
    const media = homeEntryMedia(entry);
    return {
      key: homeEntryKey(entry),
      title: String(media.title || "").slice(0, 160),
      kind: entry.kind,
      year: media.year || media.first_air_date || null,
      rating: Math.max(0, Math.min(10, Number(media.rating || 0))),
      genres: (media.genres || []).map(String).slice(0, 12),
      description: String(media.description || media.overview || "").slice(0, 800),
    };
  }).filter((item) => item.title);
}

function setAiDiscoveryState(mode, message = "") {
  const rail = document.getElementById("home-ai-rail");
  const track = document.getElementById("home-ai-track");
  const panel = document.getElementById("home-ai-state");
  const title = document.getElementById("home-ai-state-title");
  const copy = document.getElementById("home-ai-state-message");
  const retry = document.getElementById("home-ai-retry");
  if (!rail || !track || !panel) return;
  const keepVisibleRail = mode === "loading" && state.ai.recommendations.length > 0;
  rail.dataset.state = mode;
  rail.hidden = !state.ai.enabled;
  panel.hidden = mode === "ready" || keepVisibleRail;
  retry.hidden = !["error", "waiting"].includes(mode);
  document.querySelectorAll('[data-home-scroll="home-ai-track"]').forEach((button) => {
    button.hidden = mode !== "ready";
  });
  const labels = {
    loading: "Lokale Auswahl entsteht",
    waiting: "Royal KI ist aktiv",
    error: "Keine KI-Auswahl verfügbar",
  };
  if (title) title.textContent = labels[mode] || "Royal KI";
  if (copy) copy.textContent = message;
  if (mode === "loading" && !state.ai.recommendations.length) {
    track.scrollLeft = 0;
    track.dataset.homeLoopCount = "0";
    track.hidden = false;
    track.replaceChildren(...Array.from({ length: 5 }, () => {
      const skeleton = document.createElement("span");
      skeleton.className = "home-card-skeleton home-ai-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      return skeleton;
    }));
  } else if (mode !== "ready") {
    track.hidden = !state.ai.recommendations.length;
  }
  if (mode === "ready") updateHomeRailNavigation(track);
}

function renderAiDiscovery(entries, recommendations, model) {
  const rail = document.getElementById("home-ai-rail");
  const track = document.getElementById("home-ai-track");
  const note = document.getElementById("home-ai-note");
  if (!rail || !track) return;
  const byKey = new Map(entries.map((entry) => [homeEntryKey(entry), entry]));
  const specs = recommendations.map((recommendation, index) => {
    const entry = byKey.get(recommendation.key);
    if (!entry) return null;
    return {
      signature: JSON.stringify([recommendation.key, recommendation.score, recommendation.reason]),
      create: (cycle = 1) => {
        return createHomeCard(entry, 0, cycle === 1 && index < 3, index === 0 ? "spotlight-lead" : "");
      },
      update: (card) => syncHomeCardContent(card, entry, 0),
    };
  }).filter(Boolean);
  if (!specs.length) {
    setAiDiscoveryState("error", "Royal Intelligence hat Titel geliefert, die nicht mehr im aktuellen Katalog liegen.");
    return;
  }
  reconcileHomeRail(track, specs);
  track.hidden = false;
  rail.hidden = false;
  setAiDiscoveryState("ready");
  if (note) note.textContent = `${model || "Ollama"} hat ${specs.length} Titel aus Royals aktuellem Katalog eingeordnet.`;
}

async function refreshAiDiscovery(force = false) {
  const rail = document.getElementById("home-ai-rail");
  if (!state.ai.enabled) {
    if (rail) rail.hidden = true;
    return;
  }
  if (!state.ai.moduleAvailable) {
    if (rail) rail.hidden = true;
    return;
  }
  const entries = homeAllEntries();
  const candidates = aiDiscoveryCandidates();
  if (state.ai.loading) return;
  if (!candidates.length) {
    setAiDiscoveryState("waiting", "Sobald Titel geladen sind, erstellt Royal Intelligence hier eine Auswahl.");
    return;
  }
  const fingerprint = candidates.map((item) => item.key).join("|");
  if (!force && fingerprint === state.ai.lastFingerprint) return;
  const sequence = ++state.ai.requestSeq;
  state.ai.loading = true;
  if (!state.ai.recommendations.length) {
    setAiDiscoveryState(
      "loading",
      `Kandidaten werden vorbereitet … lokale KI bewertet eine kompakte Auswahl.`,
    );
  }
  try {
    const result = await api.aiRecommendations(candidates);
    if (sequence !== state.ai.requestSeq) return;
    if (!result.available || !result.recommendations?.length) {
      setAiDiscoveryState(
        "error",
        result.message || "Royal Intelligence hat noch keine verwertbare Auswahl geliefert.",
      );
      return;
    }
    state.ai.recommendations = result.recommendations;
    state.ai.lastFingerprint = fingerprint;
    renderAiDiscovery(entries, result.recommendations, result.model);
    if (result.source === "baseline" && result.refinement_status !== "error") {
      const note = document.getElementById("home-ai-note");
      if (note) note.textContent = "Basisranking ist bereit – lokale KI verfeinert die Auswahl im Hintergrund.";
      window.setTimeout(() => void refreshAiDiscovery(true), 4000);
    }
    if (result.diagnostics?.fallback) {
      const note = document.getElementById("home-ai-note");
      if (note) note.textContent = "Lokale KI derzeit nicht verfügbar – Basisranking verwendet.";
    }
  } catch (error) {
    setAiDiscoveryState("error", "Royal Intelligence ist nicht erreichbar. Einstellungen prüfen.");
    console.warn("Royal Intelligence ist nicht verfügbar:", error);
  } finally {
    state.ai.loading = false;
  }
}

window.applyAiConfig = applyAiConfig;
window.saveAiSettings = saveAiSettings;
window.testAiConnection = testAiConnection;
window.refreshAiDiscovery = refreshAiDiscovery;

document.getElementById("home-ai-retry")?.addEventListener("click", () => {
  state.ai.lastFingerprint = "";
  void refreshAiDiscovery(true);
});

const classicLoadHomeData = window.loadHomeData;
if (typeof classicLoadHomeData === "function") {
  window.loadHomeData = async function aiAwareHomeLoad(...args) {
    const result = await classicLoadHomeData(...args);
    void refreshAiDiscovery();
    return result;
  };
}
