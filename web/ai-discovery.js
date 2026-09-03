/* Optional Ollama enhancement over Royal's existing discovery candidates. */

function aiFormConfig() {
  return {
    enabled: Boolean(document.getElementById("ai-enabled")?.checked),
    url: document.getElementById("ai-url")?.value.trim() || "http://127.0.0.1:11434",
    model: document.getElementById("ai-model")?.value.trim() || "llama3.2:3b",
    timeout_seconds: 20,
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
  if (enabled !== state.ai.enabled) {
    status.textContent = enabled
      ? "Aktivierung noch speichern."
      : "Deaktivierung noch speichern.";
  } else if (enabled) {
    status.textContent = `Aktiviert · ${state.ai.model || "Ollama"} kuratiert die Discovery.`;
  } else {
    status.textContent = "Deaktiviert · Royal nutzt das klassische Ranking.";
  }
}

function applyAiConfig(config = {}) {
  state.ai.enabled = Boolean(config.enabled);
  state.ai.configured = Boolean(config.configured);
  state.ai.model = String(config.model || "");
  const enabled = document.getElementById("ai-enabled");
  const url = document.getElementById("ai-url");
  const model = document.getElementById("ai-model");
  if (enabled) enabled.checked = state.ai.enabled;
  if (url) url.value = config.url || "http://127.0.0.1:11434";
  if (model) model.value = config.model || "llama3.2:3b";
  syncAiSettingsState();
}

async function testAiConnection() {
  const button = document.getElementById("ai-test");
  const status = document.getElementById("ai-status");
  if (!button || !status) return;
  button.disabled = true;
  status.textContent = "Ollama wird geprüft …";
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
  }).slice(0, 48).map((entry) => {
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

function renderAiDiscovery(entries, recommendations, model) {
  const rail = document.getElementById("home-ai-rail");
  const track = document.getElementById("home-ai-track");
  const note = document.getElementById("home-ai-note");
  if (!rail || !track) return;
  rail.style.order = "-1";
  const byKey = new Map(entries.map((entry) => [homeEntryKey(entry), entry]));
  const specs = recommendations.map((recommendation, index) => {
    const entry = byKey.get(recommendation.key);
    if (!entry) return null;
    return {
      signature: JSON.stringify([recommendation.key, recommendation.score, recommendation.reason]),
      create: (cycle = 1) => {
        const card = createHomeCard(entry, 0, cycle === 1 && index < 3, index === 0 ? "spotlight-lead" : "");
        card.classList.add("home-ai-card");
        const art = card.querySelector(".home-card-art");
        if (art) {
          const match = document.createElement("span");
          match.className = "home-ai-match";
          match.textContent = `${recommendation.score}% Match`;
          art.appendChild(match);
        }
        const reason = document.createElement("p");
        reason.className = "home-ai-reason";
        reason.textContent = recommendation.reason;
        card.appendChild(reason);
        return card;
      },
      update: (card) => syncHomeCardContent(card, entry, 0),
    };
  }).filter(Boolean);
  if (!specs.length) {
    rail.hidden = true;
    return;
  }
  reconcileHomeRail(track, specs);
  rail.hidden = false;
  if (note) note.textContent = `${model || "Ollama"} hat ${specs.length} Titel aus Royals aktuellem Katalog eingeordnet.`;
}

async function refreshAiDiscovery(force = false) {
  const rail = document.getElementById("home-ai-rail");
  if (!state.ai.enabled) {
    if (rail) rail.hidden = true;
    return;
  }
  const entries = homeAllEntries();
  const candidates = aiDiscoveryCandidates();
  if (!candidates.length || state.ai.loading) return;
  const fingerprint = candidates.map((item) => item.key).join("|");
  if (!force && fingerprint === state.ai.lastFingerprint) return;
  const sequence = ++state.ai.requestSeq;
  state.ai.loading = true;
  try {
    const result = await api.aiRecommendations(candidates);
    if (sequence !== state.ai.requestSeq) return;
    if (!result.available || !result.recommendations?.length) {
      if (rail) rail.hidden = true;
      return;
    }
    state.ai.recommendations = result.recommendations;
    state.ai.lastFingerprint = fingerprint;
    renderAiDiscovery(entries, result.recommendations, result.model);
  } catch (error) {
    if (rail) rail.hidden = true;
    console.warn("Lokale KI-Discovery ist nicht verfügbar:", error);
  } finally {
    state.ai.loading = false;
  }
}

window.applyAiConfig = applyAiConfig;
window.saveAiSettings = saveAiSettings;
window.testAiConnection = testAiConnection;
window.refreshAiDiscovery = refreshAiDiscovery;

const classicLoadHomeData = window.loadHomeData;
if (typeof classicLoadHomeData === "function") {
  window.loadHomeData = async function aiAwareHomeLoad(...args) {
    const result = await classicLoadHomeData(...args);
    void refreshAiDiscovery();
    return result;
  };
}
