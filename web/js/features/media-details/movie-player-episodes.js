import { formatMovieTime } from "./movie-player-controls.js";

const sameEpisode = (a, b) => a.season === b.season && a.episode === b.episode;
const episodeCode = item => `S${item.season} E${item.episode}`;

function adjacentEpisode(current, items, direction) {
  const direct = items.find(item => item.season === current.season && item.episode === current.episode + direction);
  if (direct) return direct;
  // A known gap stays visible as a disabled navigation button.
  if (items.some(item => item.season === current.season && (item.episode - current.episode) * direction > 0)) return null;
  if (direction > 0) return items.find(item => item.season === current.season + 1 && item.episode === 1) || null;
  if (current.episode !== 1) return null;
  return items.filter(item => item.season === current.season - 1).at(-1) || null;
}

export function createMoviePlayerEpisodes(dialog, { client, selectEpisode }) {
  const document = dialog.ownerDocument;
  const menu = dialog.querySelector(".rd-player-episodes");
  const summary = menu.querySelector("summary span");
  const list = menu.querySelector(".rd-player-season-list");
  const status = menu.querySelector(".rd-player-season-status");
  const retry = menu.querySelector("[data-player-episodes-retry]");
  const previousButton = dialog.querySelector('[data-player-action="previous-episode"]');
  const nextButton = dialog.querySelector('[data-player-action="next-episode"]');
  let request, current, items = [], previous, next;

  function reset() {
    request?.abort();
    request = current = previous = next = null;
    items = [];
    menu.open = false;
    menu.hidden = previousButton.hidden = nextButton.hidden = true;
    previousButton.disabled = nextButton.disabled = true;
    list.replaceChildren();
    status.textContent = "";
    retry.hidden = true;
  }

  function render() {
    previous = adjacentEpisode(current, items, -1);
    next = adjacentEpisode(current, items, 1);
    previousButton.disabled = !previous;
    nextButton.disabled = !next;
    previousButton.title = previous ? `Vorherige Folge · ${episodeCode(previous)}` : "Keine vorherige Folge verfügbar";
    nextButton.title = next ? `Nächste Folge · ${episodeCode(next)}` : "Keine nächste Folge verfügbar";
    list.replaceChildren(...items.filter(item => item.season === current.season).map(item => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.playerEpisodeId = item.id;
      if (sameEpisode(item, current)) button.setAttribute("aria-current", "true");
      const title = document.createElement("span");
      title.textContent = `${episodeCode(item)} · ${item.episode_title || "Folge"}`;
      title.dataset.i18nIgnore = "";
      const state = document.createElement("small");
      state.textContent = sameEpisode(item, current) ? "Läuft gerade"
        : item.position_ticks ? `Weiterschauen ${formatMovieTime(item.position_ticks / 10_000_000)}`
          : item.played ? "Gesehen" : "Abspielen";
      button.append(title, state);
      return button;
    }));
    status.textContent = items.some(item => item.season === current.season)
      ? "" : "Keine weiteren Folgen verfügbar.";
  }

  async function show(item, pendingWrites = Promise.resolve()) {
    const open = menu.open;
    reset();
    if (item?.kind !== "episode") return;
    current = item;
    menu.hidden = previousButton.hidden = nextButton.hidden = false;
    menu.open = open;
    summary.textContent = `Staffel ${item.season}`;
    status.textContent = "Folgen werden geladen …";
    const controller = new AbortController();
    request = controller;
    try {
      await pendingWrites;
      if (request !== controller) return;
      const data = await client.get(`/api/media-center/episodes/${encodeURIComponent(item.id)}/navigation`, {
        signal: controller.signal, timeoutMs: 8_000,
      });
      if (request !== controller) return;
      if (data.profile_id !== item.profile_id || data.generation !== item.generation) {
        throw new Error("Das Jellyfin-Profil wurde geändert.");
      }
      const unique = new Map();
      for (const episode of data.items || []) {
        const key = episodeCode(episode);
        if (!unique.has(key) || episode.id === item.id) unique.set(key, { ...episode,
          profile_id: data.profile_id, generation: data.generation });
      }
      items = [...unique.values()].sort((a, b) => a.season - b.season || a.episode - b.episode);
      render();
    } catch {
      if (request !== controller) return;
      status.textContent = "Folgen konnten nicht geladen werden.";
      retry.hidden = false;
    } finally {
      if (request === controller) request = null;
    }
  }

  function choose(item) {
    if (!item || sameEpisode(item, current)) return;
    menu.open = false;
    selectEpisode(item);
  }

  return {
    show, reset,
    mount(scope) {
      scope.listen(previousButton, "click", () => choose(previous));
      scope.listen(nextButton, "click", () => choose(next));
      scope.listen(retry, "click", () => { if (current) void show(current); });
      scope.listen(list, "click", event => {
        const id = event.target.closest("[data-player-episode-id]")?.dataset.playerEpisodeId;
        choose(items.find(item => item.id === id));
      });
      scope.listen(menu, "keydown", event => {
        if (event.key !== "Escape" || !menu.open) return;
        event.preventDefault();
        event.stopPropagation();
        menu.open = false;
        menu.querySelector("summary").focus();
      });
      scope.add(reset);
    },
  };
}
