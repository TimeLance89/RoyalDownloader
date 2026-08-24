// Landscape discovery sections for the movie detail dossier.
function renderFpAbout(movie) {
  setFpDetailText("fp-detail-about-title", movie.title, "den Film");
  setFpDetailText("fp-detail-directors", (movie.directors || []).join(", "));
  setFpDetailText(
    "fp-detail-about-cast",
    (movie.cast || []).slice(0, 6).map((member) => member?.name).filter(Boolean).join(", "),
  );
  setFpDetailText("fp-detail-writers", (movie.writers || []).join(", "));
  setFpDetailText("fp-detail-about-genres", (movie.genres || []).join(", "));
  setFpDetailText("fp-detail-studios", (movie.production_companies || []).join(", "));
}

function renderFpSimilarTitles(titles) {
  const section = document.getElementById("fp-detail-similar-section");
  const container = document.getElementById("fp-detail-similar");
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
    description.textContent = item.description || "Details und verfügbare Anbieter öffnen.";
    const action = document.createElement("span");
    action.className = "detail-similar-action";
    action.textContent = "FILMAKTE ÖFFNEN →";
    copy.append(meta, title, description, action);
    card.append(artwork, copy);
    card.addEventListener("click", () => {
      document.getElementById("fp-detail-panel").scrollTop = 0;
      void selectFpRow(slug, {
        ...item,
        slug,
        cover_url: "",
        genres: [],
        runtime: "",
        hosters: [],
        metadata_source: "TMDB",
      });
    });
    container.appendChild(card);
  }
}

function renderFpExtras(movie) {
  const section = document.getElementById("fp-detail-extras-section");
  const container = document.getElementById("fp-detail-extras");
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
    image.src = api.coverUrl(movie.backdrop_url);
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
  card.addEventListener("click", () => openFpTrailerModal(movie, card, "film"));
  container.appendChild(card);
}
