import { createArtworkUrls } from "../../shared/utils/artwork-url.js";

export function queueEpisode(slug) {
  const match = String(slug || "").match(/^(.+)-s(\d{1,2})e(\d{1,3})$/i);
  return match ? { base: match[1], season: Number(match[2]), episode: Number(match[3]) } : null;
}

export function queueStatus(item) {
  return item.done ? "completed" : item.job_status || item.status || "queued";
}

export function queuePercent(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) && Number(value) >= 0
    ? Math.min(100, Number(value)) : null;
}

export function queueFocus(groups, currentId = "") {
  const items = groups.flatMap(group => group.items);
  const active = items.filter(item => ["downloading", "preparing", "cancelling"].includes(queueStatus(item)));
  return active.find(item => item.job_id === currentId) || active.find(item => queueStatus(item) === "downloading")
    || active[0] || items.find(item => ["queued", "waiting", "waiting_provider", "paused"].includes(queueStatus(item))) || null;
}

/** Read only already-loaded metadata. Exact identities avoid another show's episode artwork. */
export function queueArtwork(item, { movieState, seriesState, homeMovie, homeSeries }, origin) {
  if (!item) return [];
  const episode = queueEpisode(item.slug);
  const series = episode?.base || item.base_slug;
  const candidates = series ? [seriesState.cache[series], seriesState.current?.base_slug === series ? seriesState.current : null,
    seriesState.results.find(media => media.base_slug === series), homeSeries(series)]
    : [movieState.metadataCache[item.slug], movieState.moviesCache[item.slug],
      movieState.detail?.slug === item.slug ? movieState.detail : null, homeMovie(item.slug), item];
  const urls = createArtworkUrls(origin);
  const images = [candidates.find(media => media?.backdrop_url)?.backdrop_url,
    candidates.find(media => media?.cover_url || media?.poster_url)?.cover_url
      || candidates.find(media => media?.poster_url)?.poster_url];
  return [...new Set(images.filter(Boolean).map(url => urls.coverThumbnailCandidates(url)[0]).filter(Boolean))];
}

/** Two bounded image layers; no queue-wide image loads, no stale async commits. */
export function createQueueWallpaper(root, getImages) {
  const host = root.querySelector(".queue-wallpaper");
  const layers = [...host.querySelectorAll("img")];
  let generation = 0, key = "", current = null, visible = -1, pending = null;
  const mobile = root.ownerDocument.defaultView.matchMedia("(max-width: 820px)");
  function cancel() {
    if (pending) { pending.onload = pending.onerror = null; pending.removeAttribute("src"); }
    pending = null;
  }
  function update(item = current) {
    current = item;
    if (!mobile.matches || !document.body.classList.contains("queue-open")) return;
    let images = [];
    try { images = getImages(item); } catch { /* Missing metadata is never a download error. */ }
    const nextKey = JSON.stringify(images);
    if (nextKey === key) return;
    key = nextKey;
    const request = ++generation;
    cancel();
    if (!images.length) { layers.forEach(layer => layer.classList.remove("is-visible")); visible = -1; return; }
    // Keep the previous artwork while the replacement decodes, then crossfade.
    const layer = layers[visible === 0 ? 1 : 0];
    layer.classList.remove("is-visible");
    let index = 0;
    const load = () => {
      if (request !== generation) return;
      if (index >= images.length) {
        layers.forEach(image => image.classList.remove("is-visible")); visible = -1; cancel(); return;
      }
      pending = layer;
      layer.onload = async () => {
        try { await layer.decode(); } catch { /* onload already proves a usable image */ }
        if (request !== generation) return;
        layer.onload = layer.onerror = null; pending = null;
        layers.forEach(image => image.classList.toggle("is-visible", image === layer));
        visible = layers.indexOf(layer);
      };
      layer.onerror = () => { index++; load(); };
      layer.src = images[index];
    };
    load();
  }
  return { update, dispose() {
    generation++; cancel(); key = ""; current = null; visible = -1;
    layers.forEach(layer => { layer.classList.remove("is-visible"); layer.removeAttribute("src"); });
  } };
}
