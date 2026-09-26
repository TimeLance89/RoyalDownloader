import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Optional recommendations own their Home region and refinement lifetime. */
export function createRecommendations(root, {
  client = api, getConfig, homeAllEntries, homeEntryKey, homeEntryMedia, mediaJellyfinStatus,
  createHomeCard, syncHomeCardContent, reconcileHomeRail, updateHomeRailNavigation,
}) {
  const data = { recommendations: [], lastFingerprint: "", loading: false, requestSeq: 0 };
  const byId = id => root.querySelector(`#${id}`);
  let scope;
  let cancelRefinement = () => {};
  let cancelRequest = () => {};
  function invalidate() {
    cancelRefinement(); cancelRequest();
    data.requestSeq += 1;
    data.loading = false;
    data.recommendations = [];
    data.lastFingerprint = "";
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
    const rail = root;
    const track = byId("home-ai-track");
    const panel = byId("home-ai-state");
    const title = byId("home-ai-state-title");
    const copy = byId("home-ai-state-message");
    const retry = byId("home-ai-retry");
    if (!rail || !track || !panel) return;
    const keepVisibleRail = mode === "loading" && data.recommendations.length > 0;
    rail.dataset.state = mode;
    rail.hidden = !getConfig().enabled;
    panel.hidden = mode === "ready" || keepVisibleRail;
    retry.hidden = !["error", "waiting"].includes(mode);
    root.querySelectorAll('[data-home-scroll="home-ai-track"]').forEach((button) => {
      button.hidden = mode !== "ready";
    });
    const labels = {
      loading: "Lokale Auswahl entsteht",
      waiting: "Royal KI ist aktiv",
      error: "Keine KI-Auswahl verfügbar",
    };
    if (title) title.textContent = labels[mode] || "Royal KI";
    if (copy) copy.textContent = message;
    if (mode === "loading" && !data.recommendations.length) {
      track.scrollLeft = 0;
      track.dataset.homeLoopCount = "0";
      track.hidden = false;
      track.replaceChildren(...Array.from({ length: 5 }, () => {
        const skeleton = root.ownerDocument.createElement("span");
        skeleton.className = "home-card-skeleton home-ai-skeleton";
        skeleton.setAttribute("aria-hidden", "true");
        return skeleton;
      }));
    } else if (mode !== "ready") {
      track.hidden = !data.recommendations.length;
    }
    if (mode === "ready") updateHomeRailNavigation(track);
  }

  function renderAiDiscovery(entries, recommendations, model) {
    const rail = root;
    const track = byId("home-ai-track");
    const note = byId("home-ai-note");
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
    if (!scope?.active) return;
    const current = scope;
    const rail = root;
    if (!getConfig().enabled) {
      if (rail) rail.hidden = true;
      return;
    }
    if (!getConfig().moduleAvailable) {
      if (rail) rail.hidden = true;
      return;
    }
    const entries = homeAllEntries();
    const candidates = aiDiscoveryCandidates();
    if (data.loading) return;
    if (!candidates.length) {
      setAiDiscoveryState("waiting", "Sobald Titel geladen sind, erstellt Royal Intelligence hier eine Auswahl.");
      return;
    }
    const fingerprint = candidates.map((item) => item.key).join("|");
    if (!force && fingerprint === data.lastFingerprint) return;
    cancelRefinement();
    const request = createScope();
    const release = current.add(() => request.dispose());
    cancelRequest = release;
    const sequence = ++data.requestSeq;
    data.loading = true;
    if (!data.recommendations.length) {
      setAiDiscoveryState(
        "loading",
        `Kandidaten werden vorbereitet … lokale KI bewertet eine kompakte Auswahl.`,
      );
    }
    try {
      const result = await client.post("/api/intelligence/recommendations", { candidates }, { signal: request.signal });
      if (!current.active || sequence !== data.requestSeq) return;
      if (!result.available || !result.recommendations?.length) {
        setAiDiscoveryState(
          "error",
          result.message || "Royal Intelligence hat noch keine verwertbare Auswahl geliefert.",
        );
        return;
      }
      data.recommendations = result.recommendations;
      data.lastFingerprint = fingerprint;
      renderAiDiscovery(entries, result.recommendations, result.model);
      if (result.source === "baseline" && result.refinement_status !== "error") {
        const note = byId("home-ai-note");
        if (note) note.textContent = "Basisranking ist bereit – lokale KI verfeinert die Auswahl im Hintergrund.";
        cancelRefinement = current.timeout(() => void refreshAiDiscovery(true), 4000);
      }
      if (result.diagnostics?.fallback) {
        const note = byId("home-ai-note");
        if (note) note.textContent = "Lokale KI derzeit nicht verfügbar – Basisranking verwendet.";
      }
    } catch (error) {
      if (!current.active || sequence !== data.requestSeq) return;
      setAiDiscoveryState("error", "Royal Intelligence ist nicht erreichbar. Einstellungen prüfen.");
      console.warn("Royal Intelligence ist nicht verfügbar:", error);
    } finally {
      release();
      if (current.active && sequence === data.requestSeq) data.loading = false;
    }
  }


  return {
    invalidate,
    refresh: refreshAiDiscovery,
    configure() {
      invalidate();
      root.hidden = !getConfig().enabled || !getConfig().moduleAvailable;
      if (!root.hidden) {
        setAiDiscoveryState("waiting", "Royal Intelligence wartet auf die Titel der Startseite.");
        void refreshAiDiscovery();
      }
    },
    mount() {
      if (scope) return;
      scope = createScope();
      scope.listen(byId("home-ai-retry"), "click", () => { data.lastFingerprint = ""; void refreshAiDiscovery(true); });
      void refreshAiDiscovery();
    },
    unmount() {
      scope?.dispose(); scope = null; cancelRefinement();
      data.requestSeq += 1; data.loading = false;
      // A baseline refinement stopped by navigation must resume on the next mount.
      data.lastFingerprint = "";
    },
  };
}
