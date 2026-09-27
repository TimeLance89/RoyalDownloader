import { createScope } from "../../core/lifecycle.js";

/** Shared recommendation and trailer cards retain the existing movie/series copy and markup. */
export function createDetailDiscovery(root, { kind, coverUrl, selectFpRow, loadSeries, fpTrailerYoutubeKey, openFpTrailerModal }) {
  const document = root.ownerDocument, prefix = kind === "movie" ? "fp-detail" : "series-detail";
  const byId = id => root.querySelector(`#${id}`);
  const setText = (id, value, fallback = "—") => { byId(id).textContent = value || fallback; };
  const actions = new WeakMap();
  let scope = null;
  function renderFpAbout(movie) {
    setText("fp-detail-about-title", movie.title, "den Film");
    setText("fp-detail-directors", (movie.directors || []).join(", "));
    setText(
      "fp-detail-about-cast",
      (movie.cast || []).slice(0, 6).map((member) => member?.name).filter(Boolean).join(", "),
    );
    setText("fp-detail-writers", (movie.writers || []).join(", "));
    setText("fp-detail-about-genres", (movie.genres || []).join(", "));
    setText("fp-detail-studios", (movie.production_companies || []).join(", "));
  }

  function setSeriesDiscoveryText(id, value) {
    byId(id).textContent = value || "—";
  }

  function seriesDiscoveryStatusLabel(status) {
    return ({
      "Returning Series": "Fortlaufend",
      Ended: "Abgeschlossen",
      Canceled: "Abgebrochen",
      "In Production": "In Produktion",
      Planned: "Geplant",
      Pilot: "Pilot",
    })[status] || status || "";
  }

  function renderSeriesAbout(series) {
    const section = byId("series-detail-about-section");
    const cast = (series.cast || []).slice(0, 6).map((member) => member?.name).filter(Boolean);
    const production = [
      ...(series.production_companies || []),
      ...(series.networks || []),
      ...(series.countries || []),
    ].filter(Boolean);
    const originalStatus = [
      series.original_title,
      seriesDiscoveryStatusLabel(series.status),
    ].filter(Boolean).join(" · ");
    const hasAbout = Boolean(
      (series.creators || []).length || cast.length || (series.genres || []).length
      || production.length || originalStatus,
    );
    section.hidden = !hasAbout;
    setSeriesDiscoveryText("series-detail-about-title", series.title || "die Serie");
    setSeriesDiscoveryText("series-detail-creators", (series.creators || []).join(", "));
    setSeriesDiscoveryText("series-detail-about-cast", cast.join(", "));
    setSeriesDiscoveryText("series-detail-about-genres", (series.genres || []).join(", "));
    setSeriesDiscoveryText("series-detail-production", [...new Set(production)].join(", "));
    setSeriesDiscoveryText("series-detail-original-status", originalStatus);
  }

  function renderSimilarTitles(titles) {
    const section = byId(`${prefix}-similar-section`);
    const container = byId(`${prefix}-similar`);
    const recommendations = Array.isArray(titles)
      ? titles.filter((item) => Number(item?.tmdb_id) > 0 && item?.title && item?.backdrop_url).slice(0, 6)
      : [];
    section.hidden = !recommendations.length;
    container.replaceChildren();
    for (const item of recommendations) {
      const slug = `tmdb:${item.tmdb_id}`;
      const card = document.createElement("button");
      card.type = "button";
      card.className = "detail-similar-card";
      card.setAttribute("aria-label", `${item.title} öffnen`);

      const artwork = document.createElement("span");
      artwork.className = "detail-similar-art";
      const image = document.createElement("img");
      image.src = coverUrl(item.backdrop_url);
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      artwork.appendChild(image);

      const copy = document.createElement("span");
      copy.className = "detail-similar-copy";
      const meta = document.createElement("span");
      meta.className = "detail-similar-meta";
      meta.textContent = [
        item.year,
        item.rating ? `★ ${item.rating}` : "",
        item.original_language,
      ].filter(Boolean).join(" · ");
      const title = document.createElement("strong");
      title.textContent = item.title;
      const description = document.createElement("span");
      description.className = "detail-similar-description";
      description.textContent = item.description || (kind === "movie" ? "Details und verfügbare Anbieter öffnen." : "Staffeln und verfügbare Episoden öffnen.");
      const action = document.createElement("span");
      action.className = "detail-similar-action";
      action.textContent = kind === "movie" ? "FILMAKTE ÖFFNEN →" : "SERIENAKTE ÖFFNEN →";
      copy.append(meta, title, description, action);
      card.append(artwork, copy);
      actions.set(card, () => {
        root.querySelector(kind === "movie" ? "#fp-detail-panel" : ".series-detail-panel").scrollTop = 0;
        if (kind === "movie") void selectFpRow(slug, { ...item, slug, hosters: [], metadata_source: "TMDB" });
        else void loadSeries({ ...item, sample_slug: item.title, base_slug: "", sources: [], metadata_source: "TMDB" });
      });
      container.appendChild(card);
    }
  }

  function renderExtras(movie) {
    const section = byId(`${prefix}-extras-section`);
    const container = byId(`${prefix}-extras`);
    const key = fpTrailerYoutubeKey(movie);
    section.hidden = !key;
    container.replaceChildren();
    if (!key) return;

    const card = document.createElement("button");
    card.type = "button";
    card.className = "detail-extra-card";
    card.setAttribute("aria-label", `${movie.trailer?.name || "Trailer"} abspielen`);
    const artwork = document.createElement("span");
    artwork.className = "detail-extra-art";
    if (movie.backdrop_url) {
      const image = document.createElement("img");
      image.src = coverUrl(movie.backdrop_url);
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      artwork.appendChild(image);
    }
    const play = document.createElement("span");
    play.className = "detail-extra-play";
    play.setAttribute("aria-hidden", "true");
    play.textContent = "▶";
    artwork.appendChild(play);
    const copy = document.createElement("span");
    copy.className = "detail-extra-copy";
    const title = document.createElement("strong");
    title.textContent = movie.trailer?.name || `Trailer: ${movie.title}`;
    const meta = document.createElement("small");
    meta.textContent = movie.trailer?.official ? "OFFIZIELLER TRAILER" : "TRAILER";
    copy.append(title, meta);
    card.append(artwork, copy);
    actions.set(card, () => openFpTrailerModal(movie, card, kind === "movie" ? "film" : "series"));
    container.appendChild(card);
  }
  function renderAbout(media) { if (kind === "movie") renderFpAbout(media); else renderSeriesAbout(media); }
  function render(media) { renderSimilarTitles(media.similar_titles); renderExtras(media); renderAbout(media); }
  function mount() {
    if (scope?.active) return;
    scope = createScope();
    scope.listen(root, "click", event => {
      for (let node = event.target; node && node !== root; node = node.parentElement) {
        const action = actions.get(node); if (action) { action(); return; }
      }
    });
  }
  function unmount() { scope?.dispose(); scope = null; }
  return { render, renderAbout, renderSimilarTitles, renderExtras, mount, unmount };
}
