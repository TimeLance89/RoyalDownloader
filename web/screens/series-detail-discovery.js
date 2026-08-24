// Landscape discovery sections for the series detail dossier.
function setSeriesDiscoveryText(id, value) {
  document.getElementById(id).textContent = value || "—";
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
  const section = document.getElementById("series-detail-about-section");
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

function renderSeriesSimilarTitles(titles) {
  const section = document.getElementById("series-detail-similar-section");
  const container = document.getElementById("series-detail-similar");
  const recommendations = Array.isArray(titles)
    ? titles.filter((item) => Number(item?.tmdb_id) > 0 && item?.title && item?.backdrop_url).slice(0, 6)
    : [];
  section.hidden = !recommendations.length;
  container.replaceChildren();
  for (const item of recommendations) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "detail-similar-card";
    card.setAttribute("aria-label", `${item.title} öffnen`);
    const artwork = document.createElement("span");
    artwork.className = "detail-similar-art";
    const image = document.createElement("img");
    image.src = api.coverUrl(item.backdrop_url);
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
    description.textContent = item.description || "Staffeln und verfügbare Episoden öffnen.";
    const action = document.createElement("span");
    action.className = "detail-similar-action";
    action.textContent = "SERIENAKTE ÖFFNEN →";
    copy.append(meta, title, description, action);
    card.append(artwork, copy);
    card.addEventListener("click", () => {
      document.querySelector("#series-detail-modal .series-detail-panel").scrollTop = 0;
      void loadSeries({
        ...item,
        sample_slug: item.title,
        base_slug: "",
        cover_url: "",
        genres: [],
        sources: [],
        metadata_source: "TMDB",
      });
    });
    container.appendChild(card);
  }
}

function renderSeriesExtras(series) {
  const section = document.getElementById("series-detail-extras-section");
  const container = document.getElementById("series-detail-extras");
  const key = fpTrailerYoutubeKey(series);
  section.hidden = !key;
  container.replaceChildren();
  if (!key) return;
  const card = document.createElement("button");
  card.type = "button";
  card.className = "detail-extra-card";
  card.setAttribute("aria-label", `${series.trailer?.name || "Trailer"} abspielen`);
  const artwork = document.createElement("span");
  artwork.className = "detail-extra-art";
  if (series.backdrop_url) {
    const image = document.createElement("img");
    image.src = api.coverUrl(series.backdrop_url);
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
  title.textContent = series.trailer?.name || `Trailer: ${series.title}`;
  const meta = document.createElement("small");
  meta.textContent = series.trailer?.official ? "OFFIZIELLER TRAILER" : "TRAILER";
  copy.append(title, meta);
  card.append(artwork, copy);
  card.addEventListener("click", () => openFpTrailerModal(series, card, "series"));
  container.appendChild(card);
}

function renderSeriesDetailDiscovery(series) {
  renderSeriesSimilarTitles(series.similar_titles);
  renderSeriesExtras(series);
  renderSeriesAbout(series);
}
