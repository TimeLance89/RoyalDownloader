const COLLECTION_RESOLVE_WORKERS = 2;

function homeCollectionEntry(item) {
  return { kind: "collection", item };
}

const baseHomeEntryKey = homeEntryKey;
homeEntryKey = function movieCollectionHomeEntryKey(entry) {
  if (entry?.kind === "collection") return `collection:${entry.item.collection_id}`;
  return baseHomeEntryKey(entry);
};

const baseHomeContentKeys = homeContentKeys;
homeContentKeys = function movieCollectionHomeContentKeys(entry) {
  if (entry?.kind === "collection") return [`collection:tmdb:${entry.item.collection_id}`];
  return baseHomeContentKeys(entry);
};

const baseRefreshCatalogJellyfinStatus = refreshCatalogJellyfinStatus;
refreshCatalogJellyfinStatus = function refreshMovieCollectionJellyfinStatus(entries, render) {
  return baseRefreshCatalogJellyfinStatus(
    entries.filter((entry) => entry.kind !== "collection"), render,
  );
};

const baseOpenHomeEntry = openHomeEntry;
openHomeEntry = function openMovieCollectionHomeEntry(kind, key) {
  if (kind === "collection") return openMovieCollection(key);
  return baseOpenHomeEntry(kind, key);
};

const baseCreateHomeCard = createHomeCard;
createHomeCard = function createMovieCollectionHomeCard(entry, rank, eager, variant) {
  if (entry?.kind === "collection") return createMovieCollectionSearchCard(entry.item, eager);
  return baseCreateHomeCard(entry, rank, eager, variant);
};

function collectionArtwork(image, url, eager = false) {
  const candidates = api.coverCandidates(url);
  if (!candidates.length) {
    image.hidden = true;
    return;
  }
  let index = 0;
  image.hidden = false;
  image.loading = eager ? "eager" : "lazy";
  image.decoding = "async";
  image.src = candidates[index];
  image.onerror = () => {
    index += 1;
    if (index < candidates.length) image.src = candidates[index];
    else image.hidden = true;
  };
}

function createMovieCollectionSearchCard(collection, eager = false) {
  const card = document.createElement("article");
  card.className = "home-card movie-collection-card";
  card.dataset.kind = "collection";
  card.dataset.key = String(collection.collection_id);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "home-card-primary-action";
  button.setAttribute("aria-label", `${collection.title}, Filmreihe öffnen`);

  const art = document.createElement("span");
  art.className = "home-card-art movie-collection-card-art";
  const image = document.createElement("img");
  image.alt = "";
  collectionArtwork(image, collection.backdrop_url || collection.cover_url, eager);
  const fallback = document.createElement("span");
  fallback.className = "home-card-fallback";
  fallback.textContent = mediaCardInitials(collection.title);
  const type = document.createElement("span");
  type.className = "home-card-type movie-collection-type";
  type.textContent = "FILMREIHE";
  const mark = document.createElement("span");
  mark.className = "movie-collection-mark";
  mark.setAttribute("aria-hidden", "true");
  mark.innerHTML = "<i></i><i></i><i></i>";
  const overlay = document.createElement("span");
  overlay.className = "home-card-overlay";
  const title = document.createElement("strong");
  title.translate = false;
  title.textContent = collection.title;
  const meta = document.createElement("span");
  meta.textContent = "Komplette Reihe anzeigen";
  overlay.append(title, meta);
  art.append(fallback, image, type, mark, overlay);
  card.append(art, button);
  button.addEventListener("click", () => openMovieCollection(collection.collection_id, card));
  return card;
}

function collectionAvailabilityRecord(part) {
  return state.movieCollections.availability.get(part.slug) || { status: "checking" };
}

function collectionStatusLabel(record) {
  if (record.status === "available") return `${record.providerCount || 1} Anbieter gefunden`;
  if (record.status === "queued") return "Zur Queue hinzugefügt";
  if (record.status === "unavailable") return "Bei keinem Anbieter gefunden";
  if (record.status === "error") return "Prüfung fehlgeschlagen";
  return "Alle Anbieter werden geprüft";
}

function renderMovieCollectionFilm(part, index) {
  const record = collectionAvailabilityRecord(part);
  const card = document.createElement("article");
  card.className = `movie-collection-film is-${record.status}`;
  card.dataset.slug = part.slug;

  const order = document.createElement("span");
  order.className = "movie-collection-order";
  order.textContent = String(index + 1).padStart(2, "0");
  const poster = document.createElement("span");
  poster.className = "movie-collection-poster";
  const image = document.createElement("img");
  image.alt = "";
  collectionArtwork(image, part.cover_url);
  poster.appendChild(image);
  const copy = document.createElement("span");
  copy.className = "movie-collection-film-copy";
  const title = document.createElement("strong");
  title.textContent = part.title;
  title.translate = false;
  const meta = document.createElement("span");
  meta.textContent = [part.year, part.rating ? `★ ${part.rating}` : ""].filter(Boolean).join(" · ") || "Jahr unbekannt";
  const status = document.createElement("span");
  status.className = "movie-collection-film-status";
  status.textContent = collectionStatusLabel(record);
  copy.append(title, meta, status);

  const actions = document.createElement("span");
  actions.className = "movie-collection-film-actions";
  const open = document.createElement("button");
  open.type = "button";
  open.textContent = "Details";
  open.disabled = record.status !== "available" && record.status !== "queued";
  open.addEventListener("click", () => selectFpRow(part.slug, part));
  const download = document.createElement("button");
  download.type = "button";
  download.className = "is-primary";
  download.textContent = record.status === "queued" ? "Eingeplant" : "Herunterladen";
  download.disabled = record.status !== "available";
  download.addEventListener("click", () => queueCollectionMovies([part.slug]));
  actions.append(open, download);
  card.append(order, poster, copy, actions);
  return card;
}

function renderMovieCollection() {
  const collection = state.movieCollections.collection;
  const list = document.getElementById("movie-collection-films");
  if (!collection || !list) return;
  list.replaceChildren(...collection.parts.map(renderMovieCollectionFilm));

  const records = collection.parts.map(collectionAvailabilityRecord);
  const checked = records.filter((record) => record.status !== "checking").length;
  const available = records.filter((record) => record.status === "available").length;
  const queued = records.filter((record) => record.status === "queued").length;
  const unavailable = records.filter((record) => ["unavailable", "error"].includes(record.status)).length;
  document.getElementById("movie-collection-status").textContent = state.movieCollections.resolving
    ? `${checked} von ${collection.parts.length} Filmen geprüft`
    : `${available} downloadbar · ${queued} eingeplant · ${unavailable} nicht gefunden`;
  document.getElementById("movie-collection-progress").textContent = state.movieCollections.resolving
    ? "Jeder Film wird unabhängig bei allen aktiven Anbietern gesucht."
    : "Nicht gefundene Teile blockieren die verfügbaren Filme nicht.";
  const allButton = document.getElementById("movie-collection-download-all");
  allButton.disabled = state.movieCollections.resolving || available === 0;
  allButton.textContent = state.movieCollections.resolving
    ? "Anbieterprüfung läuft …"
    : available
      ? `${available} verfügbare ${available === 1 ? "Film" : "Filme"} herunterladen`
      : "Keine Filme downloadbar";
}

async function resolveMovieCollectionParts(collection, requestId) {
  state.movieCollections.resolving = true;
  renderMovieCollection();
  let cursor = 0;
  async function worker() {
    while (cursor < collection.parts.length && requestId === state.movieCollections.requestSeq) {
      const part = collection.parts[cursor];
      cursor += 1;
      try {
        const movie = await api.movie(part.slug, part.tmdb_id);
        if (requestId !== state.movieCollections.requestSeq) return;
        state.fp.moviesCache[part.slug] = movie;
        state.fp.metadataCache[part.slug] = { ...part, ...movie };
        state.movieCollections.availability.set(part.slug, {
          status: "available",
          providerCount: Math.max(1, Number(movie.source_count || movie.provider_count || 1)),
        });
      } catch (error) {
        if (requestId !== state.movieCollections.requestSeq) return;
        state.movieCollections.availability.set(part.slug, {
          status: error?.code === "movie_hoster_unavailable" ? "unavailable" : "error",
          message: error?.message || "Anbieterprüfung fehlgeschlagen",
        });
      }
      renderMovieCollection();
    }
  }
  await Promise.all(Array.from(
    { length: Math.min(COLLECTION_RESOLVE_WORKERS, collection.parts.length) },
    () => worker(),
  ));
  if (requestId !== state.movieCollections.requestSeq) return;
  state.movieCollections.resolving = false;
  renderMovieCollection();
}

async function openMovieCollection(collectionId, trigger = null) {
  const requestId = ++state.movieCollections.requestSeq;
  state.movieCollections.activeId = Number(collectionId);
  state.movieCollections.collection = null;
  state.movieCollections.availability = new Map();
  state.movieCollections.resolving = false;
  document.getElementById("movie-collection-title").textContent = "Filmreihe wird geladen";
  document.getElementById("movie-collection-description").textContent = "";
  document.getElementById("movie-collection-status").textContent = "TMDB-Daten werden geladen …";
  document.getElementById("movie-collection-progress").textContent = "";
  document.getElementById("movie-collection-films").replaceChildren();
  document.getElementById("movie-collection-download-all").disabled = true;
  openMediaModal("movie-collection-modal", trigger);
  try {
    const response = await api.movieCollection(collectionId);
    if (requestId !== state.movieCollections.requestSeq) return;
    const collection = response.collection;
    state.movieCollections.collection = collection;
    document.getElementById("movie-collection-title").textContent = collection.title;
    document.getElementById("movie-collection-description").textContent = collection.description
      || `${collection.part_count} Filme in Veröffentlichungsreihenfolge.`;
    const cover = document.getElementById("movie-collection-cover");
    cover.alt = `Cover von ${collection.title}`;
    collectionArtwork(cover, collection.cover_url, true);
    const hero = document.getElementById("movie-collection-hero");
    const backdrop = api.coverUrl(collection.backdrop_url || "");
    hero.style.setProperty("--collection-backdrop", backdrop ? `url("${backdrop.replace(/"/g, "%22")}")` : "none");
    collection.parts.forEach((part) => {
      state.movieCollections.availability.set(part.slug, { status: "checking" });
      state.fp.metadataCache[part.slug] = { ...part, details_loaded: false };
    });
    renderMovieCollection();
    void resolveMovieCollectionParts(collection, requestId);
  } catch (error) {
    if (requestId !== state.movieCollections.requestSeq) return;
    document.getElementById("movie-collection-title").textContent = "Filmreihe nicht verfügbar";
    document.getElementById("movie-collection-status").textContent = error?.message || "TMDB konnte die Reihe nicht laden.";
  }
}

async function queueCollectionMovies(slugs) {
  const available = slugs.filter(
    (slug) => collectionAvailabilityRecord({ slug }).status === "available",
  );
  if (!available.length) return;
  const button = document.getElementById("movie-collection-download-all");
  button.disabled = true;
  try {
    const response = await api.queueAdd(available, {}, "collection");
    refreshQueueUiAfterChange(response);
    available.forEach((slug) => {
      if (state.queuedSlugs.has(slug)) {
        state.movieCollections.availability.set(slug, { status: "queued" });
      }
    });
  } catch (error) {
    document.getElementById("movie-collection-progress").textContent =
      `Download konnte nicht eingeplant werden: ${error?.message || "Unbekannter Fehler"}`;
  }
  renderMovieCollection();
}

document.getElementById("movie-collection-download-all")?.addEventListener("click", () => {
  const collection = state.movieCollections.collection;
  if (!collection) return;
  void queueCollectionMovies(collection.parts.map((part) => part.slug));
});
