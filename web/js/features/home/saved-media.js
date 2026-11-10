import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { appStore } from "../../core/store.js";

const TRACK_ID = "home-saved-track";
const MAX_CARDS = 36;
const ARTWORK_BATCH = 12;

/** Saved wishes are scoped by the server to the current RD profile, not Jellyfin. */
export function savedHomeEntries(raw, max = MAX_CARDS) {
  if (!Array.isArray(raw)) return [];
  const seen = new Set();
  return raw
    .filter((wish) => {
      const id = Number(wish?.tmdb_id);
      return (wish?.media_type === "movie" || wish?.media_type === "tv")
        && Number.isSafeInteger(id) && id > 0
        && typeof wish.title === "string" && wish.title.trim().length > 0;
    })
    .slice()
    .sort((a, b) => (Number(b.created_at) || 0) - (Number(a.created_at) || 0))
    .filter((wish) => {
      const key = wish.media_type + ":" + wish.tmdb_id;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, max)
    .map((wish) => {
      const tmdbId = Number(wish.tmdb_id);
      const kind = wish.media_type === "movie" ? "movie" : "series";
      const slug = "tmdb:" + tmdbId;
      return {
        kind,
        item: {
          slug, base_slug: slug, sample_slug: slug,
          tmdb_id: tmdbId,
          media_type: wish.media_type,
          title: wish.title.trim().slice(0, 240),
          year: "", cover_url: "", backdrop_url: "",
          tmdb_discovery: true,
          saved_media: true,
          metadata_source: "TMDB",
          genres: [],
        },
      };
    });
}

/**
 * Self-contained personal rail. Unlike discovery recommendations, this list
 * displays the owner's exact wishes even before a Jellyfin item is playable.
 * All requests are cancelled on profile switch, visibility disposal or refresh.
 */
export function createHomeSavedMedia(root, {
  client = api,
  store = appStore,
  getOwner = () => store.get().user?.id || "",
  renderHomeRail,
  updateNavigation = () => {},
} = {}) {
  const document = root.ownerDocument;
  let scope = null;
  let owner = "";
  let entries = [];
  let listRequest = null, artworkRequest = null;
  let generation = 0;

  function connected() {
    const section = root.querySelector('[data-home-rail="saved"]');
    const track = root.querySelector("#" + TRACK_ID);
    return { section, track };
  }

  function paint() {
    const { section, track } = connected();
    if (!section || !track) return;
    const authorized = Boolean(owner && owner === String(getOwner() || ""));
    const current = authorized ? entries : [];
    section.hidden = !current.length;
    renderHomeRail(TRACK_ID, current, { showEmpty: false });
    updateNavigation(track);
  }

  function resetOwner(next = String(getOwner() || "")) {
    if (owner === next) return false;
    generation += 1;
    listRequest?.abort();
    artworkRequest?.abort();
    listRequest = artworkRequest = null;
    owner = next;
    entries = [];
    paint();
    return true;
  }

  function stillCurrent(scopeOwner, controller, epoch, requestType = "list") {
    return scope?.active && generation === epoch
      && owner === scopeOwner && String(getOwner() || "") === scopeOwner
      && (requestType === "list" ? listRequest === controller : artworkRequest === controller)
      && !controller.signal.aborted;
  }

  async function enrich(scopeOwner, epoch) {
    artworkRequest?.abort();
    const controller = new AbortController();
    artworkRequest = controller;
    const wanted = entries.filter((entry) => entry?.item?.saved_media);
    const isCurrent = () => stillCurrent(scopeOwner, controller, epoch, "artwork");
    try {
      for (let offset = 0; offset < wanted.length && isCurrent(); offset += ARTWORK_BATCH) {
        const batch = wanted.slice(offset, offset + ARTWORK_BATCH);
        const movies = batch.filter((entry) => entry.kind === "movie");
        const shows = batch.filter((entry) => entry.kind === "series");
        const tasks = [];
        if (movies.length) tasks.push(client.post("/api/tmdb/movies", {
          background: true,
          items: movies.map(({ item }) => ({
            slug: item.slug, title: item.title, tmdb_id: item.tmdb_id, year: item.year,
          })),
        }, { signal: controller.signal, timeoutMs: 15_000 }).then((response) => {
          if (!isCurrent()) return;
          for (const { item } of movies) {
            const metadata = response?.movies?.[item.slug];
            if (metadata) Object.assign(item, metadata, {
              slug: "tmdb:" + item.tmdb_id, tmdb_id: item.tmdb_id,
              saved_media: true, tmdb_discovery: true, metadata_source: "TMDB",
            });
          }
        }));
        if (shows.length) tasks.push(client.post("/api/tmdb/series", {
          items: shows.map(({ item }) => ({
            base_slug: item.base_slug, title: item.title, tmdb_id: item.tmdb_id, year: item.year,
          })),
        }, { signal: controller.signal, timeoutMs: 15_000 }).then((response) => {
          if (!isCurrent()) return;
          for (const { item } of shows) {
            const metadata = response?.series?.[item.base_slug];
            if (metadata) Object.assign(item, metadata, {
              base_slug: "tmdb:" + item.tmdb_id, sample_slug: "tmdb:" + item.tmdb_id,
              tmdb_id: item.tmdb_id, saved_media: true, tmdb_discovery: true, metadata_source: "TMDB",
            });
          }
        }));
        const results = await Promise.allSettled(tasks);
        if (!isCurrent()) return;
        if (results.some((result) => result.status === "rejected")) {
          // Saved titles remain usable without TMDB artwork. A later poll retries.
          console.warn("Merkliste: Einige Bilder konnten nicht geladen werden.");
        }
        paint();
      }
    } finally {
      if (artworkRequest === controller) artworkRequest = null;
    }
  }

  async function refresh() {
    if (!scope?.active) return;
    resetOwner();
    if (!owner || document.hidden) return;
    const scopeOwner = owner;
    const epoch = ++generation;
    listRequest?.abort();
    artworkRequest?.abort();
    const controller = new AbortController();
    listRequest = controller;
    try {
      const payload = await client.get("/api/me/saved-media", {
        signal: controller.signal,
        timeoutMs: 12_000,
        headers: { "X-Royal-Profile": scopeOwner },
      });
      if (!stillCurrent(scopeOwner, controller, epoch)) return;
      // The cookie may have been switched in another tab before app state caught up.
      // Never render the response if the server does not attest the same owner.
      if (String(payload?.owner_user_id || "") !== scopeOwner) {
        entries = [];
        paint();
        return;
      }
      entries = savedHomeEntries(payload?.items);
      paint();
      if (entries.length) void enrich(scopeOwner, epoch);
    } catch (error) {
      if (!controller.signal.aborted && stillCurrent(scopeOwner, controller, epoch)
          && (error?.status === 401 || error?.status === 403)) {
        entries = [];
        paint();
      }
      // Other failures retain the last successfully loaded wishes and retry.
    } finally {
      if (listRequest === controller) listRequest = null;
    }
  }

  function clear() {
    generation += 1;
    listRequest?.abort();
    artworkRequest?.abort();
    listRequest = artworkRequest = null;
    owner = "";
    entries = [];
    paint();
  }

  return {
    refresh,
    mount() {
      if (scope?.active) return;
      scope = createScope();
      resetOwner();
      scope.listen(document, "royal:saved-media-changed", () => { void refresh(); });
      scope.listen(document, "visibilitychange", () => {
        if (!document.hidden) void refresh();
      });
      scope.add(store.subscribe((next, previous) => {
        const nextOwner = String(getOwner() || "");
        if (nextOwner !== owner) {
          resetOwner(nextOwner);
          void refresh();
        } else if (next.navigation === "home" && previous.navigation !== "home") {
          void refresh();
        }
      }));
      scope.interval(() => { void refresh(); }, 60_000);
      void refresh();
    },
    unmount() {
      scope?.dispose();
      scope = null;
      clear();
    },
  };
}
