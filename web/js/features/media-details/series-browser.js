import { appStore } from "../../core/store.js";
import { playbackIdentity, playbackDenied } from "../../shared/playback-access.js";
import { formatMovieTime } from "./movie-player-controls.js";

const ticksPerSecond = 10_000_000;
const keyOf = (season, episode) => `${season}:${episode}`;
const episodeNumber = ({ season, episode }) => `S${season} E${episode}`;
const watchedAt = item => Date.parse(item?.last_played) || 0;

export function createSeriesBrowser(root, { client, canPlay, openItem, chooseDownload, canDownload, store = appStore }) {
  const document = root.ownerDocument;
  const switcher = root.querySelector("#series-view-switch");
  const picker = root.querySelector("#series-season-picker");
  const select = root.querySelector("#series-active-season");
  if (!select) return null;
  const watch = root.querySelector("#series-watch-episodes");
  const downloads = root.querySelector("#series-download-episodes");
  const dock = root.querySelector("#series-download-dock");
  const emptyDownloads = root.querySelector("#series-no-downloads");
  let scope, request, series, identity, query, context;
  let mode = "downloads", season, modeChosen = false, seasonChosen = false;
  let inventory = new Map(), watchSignature = "", seasonSignature = "";

  function node(tag, className, text = "") {
    const element = document.createElement(tag);
    element.className = className;
    element.textContent = text;
    return element;
  }

  function entries() {
    const merged = new Map([...inventory].map(([key, item]) => [key, { ...item, item }]));
    for (const group of series?.seasons || []) {
      for (const episode of group.episodes || []) {
        const key = keyOf(group.season, episode.episode);
        merged.set(key, { season: group.season, episode: episode.episode, ...merged.get(key), download: episode });
      }
    }
    return [...merged.values()].sort((a, b) => a.season - b.season || a.episode - b.episode);
  }

  function nextEpisode(all) {
    const selected = all.find(row => row.item?.id === series?.jellyfin_episode_id);
    if (selected) return selected;
    const partial = all.filter(row => row.item?.position_ticks > 0)
      .sort((a, b) => watchedAt(b.item) - watchedAt(a.item))[0];
    if (partial) return partial;
    const regular = all.some(row => row.season > 0) ? all.filter(row => row.season > 0) : all;
    const latest = regular.filter(row => row.item?.played).sort((a, b) => watchedAt(b.item) - watchedAt(a.item)
      || b.season - a.season || b.episode - a.episode)[0];
    if (!latest) return regular[0];
    const next = regular[regular.indexOf(latest) + 1];
    if (next?.season === latest.season && next.episode > latest.episode + 1) {
      return { season: latest.season, episode: latest.episode + 1 };
    }
    return next || regular.find(row => !row.item?.played) || regular.find(row => row.item);
  }

  function playButton(row, featured = false) {
    const item = row.item;
    const time = item?.position_ticks ? formatMovieTime(item.position_ticks / ticksPerSecond) : "";
    const playable = Boolean(item);
    const downloadable = !playable && canDownload(row.download);
    const label = playable ? (time ? `▶ Weiterschauen ${time}` : item.played ? "▶ Erneut ansehen" : "▶ Abspielen")
      : downloadable ? "↓ Zum Download" : row.download?.unreleased ? "Noch nicht erschienen" : "Nicht abspielbar";
    const button = node("button", featured ? "series-next-action btn btn-accent" : "series-watch-action btn btn-ghost", label);
    button.type = "button";
    button.disabled = !playable && !downloadable;
    button.dataset.episodeKey = `${keyOf(row.season, row.episode)}:${featured ? "featured" : "row"}`;
    button.setAttribute("aria-label", `${episodeNumber(row)} ${label}`);
    button.addEventListener("click", () => {
      if (playable && canPlay()) {
        modeChosen = seasonChosen = true;
        openItem({ ...item, ...context }, button);
      } else if (downloadable) {
        mode = "downloads";
        modeChosen = seasonChosen = true;
        season = row.season;
        render();
        chooseDownload(row.download.slug);
      }
    });
    return button;
  }

  function renderWatch(all, next) {
    const rows = all.filter(row => row.season === season);
    const signature = JSON.stringify([season, context, next, rows.map(row => [row.season, row.episode,
      row.item, row.download?.title, row.download?.name, row.download?.unreleased, canDownload(row.download)]),
      canDownload(next?.download)]);
    if (signature === watchSignature) return;
    watchSignature = signature;
    const focused = watch.contains(document.activeElement) ? document.activeElement.dataset.episodeKey : null;
    const content = document.createDocumentFragment();
    if (next) {
      const featured = node("div", "series-next-episode");
      const copy = node("div", "series-next-copy");
      const heading = next.item?.position_ticks ? "Dein Wiedereinstieg" : next.item?.played ? "Noch einmal ansehen" : "Als Nächstes";
      copy.append(node("span", "series-next-kicker", heading),
        node("strong", "", `${episodeNumber(next)} · ${next.item?.episode_title || next.download?.title || next.download?.name || "Folge"}`));
      featured.append(copy, playButton(next, true));
      content.append(featured);
    }
    const list = node("ul", "series-watch-list");
    for (const row of rows) {
      const item = row.item;
      const card = node("li", "series-watch-row");
      const art = node("div", "series-watch-art");
      if (item?.has_image) {
        const image = node("img", "");
        image.alt = "";
        image.loading = "lazy";
        image.src = `/api/media-center/continue-watching/${encodeURIComponent(item.id)}/image`;
        image.addEventListener("error", () => image.remove(), { once: true });
        art.append(image);
      }
      art.append(node("span", "", episodeNumber(row)));
      if (item?.position_ticks && item.duration_ticks) {
        const line = node("div", "series-watch-progress");
        line.style.setProperty("--episode-played", `${100 * item.position_ticks / item.duration_ticks}%`);
        art.append(line);
      }
      const copy = node("div", "series-watch-copy");
      copy.append(node("strong", "", item?.episode_title || row.download?.title || row.download?.name || `Folge ${row.episode}`));
      const runtime = item?.duration_ticks ? `${Math.round(item.duration_ticks / ticksPerSecond / 60)} Min.` : "";
      const status = item ? (item.played && !item.position_ticks ? "Gesehen" : "In Jellyfin")
        : row.download?.in_jellyfin ? "Im Profil nicht abspielbar"
          : row.download?.unreleased ? "Demnächst" : "Fehlt in Jellyfin";
      copy.append(node("small", "", [status, runtime].filter(Boolean).join(" · ")));
      card.append(art, copy, playButton(row));
      list.append(card);
    }
    content.append(list);
    watch.replaceChildren(content);
    if (focused) {
      const buttons = [...watch.querySelectorAll("[data-episode-key]")];
      const previous = buttons.find(button => button.dataset.episodeKey === focused)
        || buttons.find(button => button.dataset.episodeKey === focused.replace(/:featured$/, ":row"));
      previous?.focus({ preventScroll: true });
    }
  }

  function render() {
    const all = entries();
    const next = nextEpisode(all);
    const seasons = [...new Set(all.map(row => Number(row.season)))];
    const available = inventory.size > 0 && canPlay();
    const hasDownloads = !series?.jellyfin_inventory
      || all.some(row => !row.item && row.download && !row.download.in_jellyfin);
    if (!available) mode = "downloads";
    else if (!modeChosen || !hasDownloads) mode = "watch";
    if (!seasons.includes(Number(season)) || (available && !seasonChosen)) {
      season = available && next ? Number(next.season) : seasons[0];
    }
    const signature = seasons.join(",");
    if (signature !== seasonSignature) {
      seasonSignature = signature;
      select.replaceChildren(...seasons.map(number => {
        const option = node("option", "", number === 0 ? "Specials" : `Staffel ${number}`);
        option.value = number;
        return option;
      }));
    }
    select.value = season ?? "";
    switcher.hidden = !available || !hasDownloads;
    picker.hidden = !seasons.length;
    for (const button of switcher.querySelectorAll("[data-series-mode]")) {
      button.setAttribute("aria-pressed", String(button.dataset.seriesMode === mode));
    }
    watch.hidden = mode !== "watch";
    downloads.hidden = dock.hidden = mode !== "downloads";
    const providerRows = [...downloads.querySelectorAll(".season-row")];
    for (const row of providerRows) row.hidden = Number(row.dataset.season) !== Number(season);
    emptyDownloads.hidden = !seasons.length || providerRows.some(row => !row.hidden)
      || Boolean(downloads.querySelector("#series-tiles > .series-loading"));
    if (!watch.hidden) renderWatch(all, next);
  }

  function reset() {
    request?.abort();
    request = series = identity = query = context = null;
    mode = "downloads";
    season = undefined;
    modeChosen = seasonChosen = false;
    inventory = new Map();
    watchSignature = "";
    dock.dataset.hasSelection = "false";
    watch.replaceChildren();
    render();
  }

  function acceptInventory(data) {
    context = { profile_id: data.profile_id, generation: data.generation };
    inventory = new Map();
    for (const item of data.items || []) {
      const key = keyOf(item.season, item.episode);
      const existing = inventory.get(key);
      if (!existing || item.id === series?.jellyfin_episode_id
          || (existing.id !== series?.jellyfin_episode_id
            && (watchedAt(item) > watchedAt(existing) || (item.position_ticks && !existing.position_ticks)))) {
        inventory.set(key, item);
      }
    }
  }

  async function load(url) {
    request?.abort();
    const current = new AbortController();
    request = current;
    try {
      const data = await client.get(url, { signal: current.signal, timeoutMs: 9_000 });
      if (request !== current) return;
      acceptInventory(data);
      render();
    } catch (error) {
      if (request === current && playbackDenied(error)) { inventory = new Map(); context = null; render(); }
      // Jellyfin failures leave the independent download controls usable.
    } finally {
      if (request === current) request = null;
    }
  }

  function update(next) {
    if (!next) return;
    const id = next.base_slug || next.sample_slug || next.title;
    if (id !== identity) reset();
    identity = id;
    series = next;
    if (next.jellyfin_inventory && next.jellyfin_episode_id) {
      const url = `/api/media-center/episodes/${encodeURIComponent(next.jellyfin_episode_id)}/navigation`;
      if (query !== url) {
        query = url;
        acceptInventory(next.jellyfin_inventory);
      }
      render();
      return;
    }
    render();
    if (!next.title || !scope?.active || !canPlay()) return;
    const params = new URLSearchParams({ title: next.title });
    if (Number(next.tmdb_id) > 0) params.set("tmdb_id", next.tmdb_id);
    for (const alias of [...new Set([next.original_title, ...(next.aliases || [])].filter(Boolean))].slice(0, 8)) params.append("aliases", alias);
    const key = `/api/media-center/series/episodes?${params}`;
    if (key !== query) {
      if (query) {
        inventory = new Map();
        context = null;
        render();
      }
      query = key;
      void load(query);
    }
  }

  return {
    update, close: reset, keepDownloads() { if (mode === "downloads") modeChosen = true; },
    mount(owner) {
      scope = owner;
      const clearPersonal = () => {
        const next = series && { ...series, jellyfin_inventory: null, jellyfin_episode_id: null };
        reset();
        if (next) update(next);
      };
      owner.add(store.subscribe((next, previous) => {
        if (playbackIdentity(next.user) !== playbackIdentity(previous.user)) clearPersonal();
      }));
      owner.listen(document, "royal:media-center-changed", clearPersonal);
      owner.listen(select, "change", () => { seasonChosen = true; season = Number(select.value); render(); });
      owner.listen(switcher, "click", event => {
        const choice = event.target.closest("[data-series-mode]")?.dataset.seriesMode;
        if (!choice) return;
        modeChosen = true;
        mode = choice;
        render();
      });
      owner.listen(document, "royal:playback-closed", () => {
        if (!root.hidden && query && canPlay()) void load(query);
      });
    },
  };
}
