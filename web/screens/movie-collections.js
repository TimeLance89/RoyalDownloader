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
  return state.movieCollections.availability.get(part.slug) || {
    libraryStatus: "checking",
    providerStatus: "waiting",
    queueStatus: "idle",
    selected: false,
    providerCount: 0,
    message: "",
  };
}

function updateCollectionRecord(slug, changes) {
  const current = collectionAvailabilityRecord({ slug });
  state.movieCollections.availability.set(slug, { ...current, ...changes });
}

function collectionReleaseIsFuture(part) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(part.release_date || "")) return false;
  return new Date(`${part.release_date}T23:59:59`).getTime() > Date.now();
}

function collectionPrimaryStatus(record) {
  if (record.queueStatus === "adding") return "adding";
  if (record.queueStatus === "queued") return "queued";
  if (record.queueStatus === "skipped") return "skipped";
  if (record.queueStatus === "error") return "error";
  if (record.libraryStatus === "owned") return "owned";
  return record.providerStatus;
}

function collectionLibraryLabel(status) {
  const labels = {
    checking: "Jellyfin wird geprüft",
    owned: "In Jellyfin",
    missing: "Fehlt in Jellyfin",
    unavailable: "Jellyfin nicht erreichbar",
    blocked: "Jellyfin-Prüfung blockiert",
    unconfigured: "Jellyfin nicht verbunden",
    ambiguous: "Jellyfin-Zuordnung unklar",
  };
  return labels[status] || labels.unavailable;
}

function collectionProviderLabel(record) {
  if (record.providerStatus === "available") {
    return `${record.providerCount || 1} Anbieter`;
  }
  const labels = {
    waiting: "Wartet auf Jellyfin-Prüfung",
    checking: "Alle Anbieter werden geprüft",
    unavailable: "Bei keinem Anbieter gefunden",
    error: "Anbieterprüfung fehlgeschlagen",
    skipped: "Anbieterprüfung nicht nötig",
    blocked: "Download bis zur Jellyfin-Prüfung gesperrt",
    future: "Noch nicht veröffentlicht",
  };
  return labels[record.providerStatus] || "Anbieterstatus offen";
}

function collectionQueueLabel(record) {
  const labels = {
    adding: "Wird eingeplant",
    queued: "Download eingeplant",
    skipped: record.message || "Nicht eingeplant",
    error: record.message || "Queue-Anfrage fehlgeschlagen",
  };
  return labels[record.queueStatus] || "";
}

function collectionLibraryAllowsDownload(status) {
  return ["missing", "unconfigured"].includes(status);
}

function collectionSelectable(record) {
  return record.providerStatus === "available"
    && collectionLibraryAllowsDownload(record.libraryStatus)
    && !["adding", "queued"].includes(record.queueStatus);
}

function setCollectionSelected(slug, selected) {
  const record = collectionAvailabilityRecord({ slug });
  if (!collectionSelectable(record)) return;
  updateCollectionRecord(slug, { selected: Boolean(selected), queueStatus: "idle", message: "" });
  renderMovieCollection();
}

function renderMovieCollectionFilm(part, index) {
  const record = collectionAvailabilityRecord(part);
  const primaryStatus = collectionPrimaryStatus(record);
  const card = document.createElement("article");
  card.className = `movie-collection-film is-${primaryStatus}`;
  card.dataset.slug = part.slug;

  const selection = document.createElement("label");
  selection.className = "movie-collection-selection";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = Boolean(record.selected);
  checkbox.disabled = !collectionSelectable(record);
  checkbox.setAttribute("aria-label", `${part.title} für den Download auswählen`);
  checkbox.addEventListener("change", () => setCollectionSelected(part.slug, checkbox.checked));
  const selectionMark = document.createElement("span");
  selectionMark.setAttribute("aria-hidden", "true");
  selection.append(checkbox, selectionMark);
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
  const statuses = document.createElement("span");
  statuses.className = "movie-collection-film-statuses";
  const library = document.createElement("span");
  library.className = `is-library-${record.libraryStatus}`;
  library.textContent = collectionLibraryLabel(record.libraryStatus);
  const provider = document.createElement("span");
  provider.className = `is-provider-${record.providerStatus}`;
  provider.textContent = collectionProviderLabel(record);
  statuses.append(library, provider);
  const queueMessage = collectionQueueLabel(record);
  if (queueMessage) {
    const queue = document.createElement("span");
    queue.className = `is-queue-${record.queueStatus}`;
    queue.textContent = queueMessage;
    statuses.appendChild(queue);
  }
  copy.append(title, meta, statuses);

  const actions = document.createElement("span");
  actions.className = "movie-collection-film-actions";
  const open = document.createElement("button");
  open.type = "button";
  open.textContent = "Details";
  open.disabled = record.providerStatus !== "available";
  open.addEventListener("click", () => selectFpRow(part.slug, part));
  const download = document.createElement("button");
  download.type = "button";
  download.className = "is-primary";
  download.textContent = record.queueStatus === "queued" ? "Eingeplant" : "Einzeln laden";
  download.disabled = !collectionSelectable(record) || state.movieCollections.queuePending;
  if (record.providerStatus === "blocked") {
    download.textContent = "Prüfen & laden";
    download.disabled = record.libraryStatus === "checking" || state.movieCollections.queuePending;
    download.addEventListener("click", () => void retryMovieCollectionJellyfinPart(part));
  } else if (["unavailable", "error"].includes(record.providerStatus)) {
    download.textContent = "Erneut prüfen";
    download.disabled = state.movieCollections.resolving;
    download.addEventListener("click", () => void retryMovieCollectionPart(part));
  } else download.addEventListener("click", () => queueCollectionMovies([part.slug]));
  actions.append(open, download);
  card.append(selection, order, poster, copy, actions);
  return card;
}

function renderMovieCollection() {
  const collection = state.movieCollections.collection;
  const list = document.getElementById("movie-collection-films");
  if (!collection || !list) return;
  list.replaceChildren(...collection.parts.map(renderMovieCollectionFilm));

  const records = collection.parts.map(collectionAvailabilityRecord);
  const libraryPending = records.filter((record) => record.libraryStatus === "checking").length;
  const providerCandidates = records.filter((record) => !["skipped", "future"].includes(record.providerStatus));
  const providerChecked = providerCandidates.filter(
    (record) => !["waiting", "checking"].includes(record.providerStatus),
  ).length;
  const owned = records.filter((record) => record.libraryStatus === "owned").length;
  const libraryUncertain = records.filter(
    (record) => ["unavailable", "blocked", "ambiguous"].includes(record.libraryStatus),
  ).length;
  const available = records.filter(collectionSelectable).length;
  const selected = records.filter((record) => record.selected && collectionSelectable(record)).length;
  const queued = records.filter((record) => record.queueStatus === "queued").length;
  const unavailable = records.filter(
    (record) => ["unavailable", "error"].includes(record.providerStatus),
  ).length;
  const future = records.filter((record) => record.providerStatus === "future").length;
  state.movieCollections.resolving = libraryPending > 0
    || providerCandidates.some((record) => ["waiting", "checking"].includes(record.providerStatus));
  document.getElementById("movie-collection-status").textContent = libraryPending
    ? `Jellyfin-Status für ${collection.parts.length} Filme wird geprüft`
    : libraryUncertain
      ? `${libraryUncertain} ${libraryUncertain === 1 ? "Jellyfin-Prüfung ist" : "Jellyfin-Prüfungen sind"} noch offen`
    : state.movieCollections.resolving
      ? `${providerChecked} von ${providerCandidates.length} Anbieterprüfungen abgeschlossen`
      : `${collection.parts.length} Filme vollständig geprüft`;
  document.getElementById("movie-collection-progress").textContent = libraryPending
    ? "Vorhandene Filme werden nicht erneut bei den Anbietern gesucht."
    : libraryUncertain
      ? "Betroffene Filme bleiben gesperrt, bis Jellyfin ihren Bestand sicher bestätigt hat."
    : state.movieCollections.resolving
      ? "Gefundene Filme werden sofort auswählbar; Fehler bleiben auf den einzelnen Titel begrenzt."
      : "Nur ausgewählte, verfügbare und noch nicht vorhandene Filme gehen in die Queue.";

  const counts = document.getElementById("movie-collection-counts");
  counts.replaceChildren();
  [
    [owned, "in Jellyfin", "owned"],
    [libraryUncertain, "Jellyfin offen", "library-open"],
    [available, "downloadbar", "available"],
    [queued, "eingeplant", "queued"],
    [unavailable, "nicht gefunden", "unavailable"],
    [future, "noch nicht erschienen", "future"],
  ].filter(([count]) => count > 0).forEach(([count, label, kind]) => {
    const badge = document.createElement("span");
    badge.className = `is-${kind}`;
    badge.textContent = `${count} ${label}`;
    counts.appendChild(badge);
  });

  const selectAll = document.getElementById("movie-collection-select-all");
  const everyAvailableSelected = available > 0 && available === selected;
  selectAll.disabled = available === 0 || state.movieCollections.queuePending;
  selectAll.textContent = everyAvailableSelected ? "Auswahl aufheben" : "Verfügbare auswählen";
  const allButton = document.getElementById("movie-collection-download-all");
  allButton.disabled = selected === 0 || state.movieCollections.queuePending;
  allButton.textContent = state.movieCollections.queuePending
    ? "Wird eingeplant …"
    : selected
      ? `${selected} ${selected === 1 ? "Film" : "Filme"} herunterladen`
      : "Auswahl herunterladen";
}

async function resolveMovieCollectionPart(part, requestId) {
  updateCollectionRecord(part.slug, {
    providerStatus: "checking", selected: false, queueStatus: "idle", message: "",
  });
  renderMovieCollection();
  try {
    const movie = await api.movie(part.slug, part.tmdb_id);
    if (requestId !== state.movieCollections.requestSeq) return;
    state.fp.moviesCache[part.slug] = movie;
    state.fp.metadataCache[part.slug] = { ...part, ...movie };
    updateCollectionRecord(part.slug, {
      providerStatus: "available",
      providerCount: Math.max(1, Number(movie.source_count || movie.provider_count || 1)),
      selected: true,
    });
  } catch (error) {
    if (requestId !== state.movieCollections.requestSeq) return;
    updateCollectionRecord(part.slug, {
      providerStatus: error?.code === "movie_hoster_unavailable" ? "unavailable" : "error",
      selected: false,
      message: error?.message || "Anbieterprüfung fehlgeschlagen",
    });
  }
  renderMovieCollection();
}

async function resolveMovieCollectionParts(parts, requestId) {
  let cursor = 0;
  async function worker() {
    while (cursor < parts.length && requestId === state.movieCollections.requestSeq) {
      const part = parts[cursor];
      cursor += 1;
      await resolveMovieCollectionPart(part, requestId);
    }
  }
  await Promise.all(Array.from(
    { length: Math.min(COLLECTION_RESOLVE_WORKERS, parts.length) },
    () => worker(),
  ));
  if (requestId !== state.movieCollections.requestSeq) return;
  renderMovieCollection();
}

async function checkMovieCollectionJellyfin(collection, requestId) {
  const requests = collection.parts.map(movieCollectionJellyfinRequest);
  const batches = [];
  for (let index = 0; index < requests.length; index += 100) {
    batches.push(requests.slice(index, index + 100));
  }
  const responses = await Promise.allSettled(
    batches.map((batch) => api.jellyfinMatches(batch)),
  );
  if (requestId !== state.movieCollections.requestSeq) return [];
  const libraryStatusBySlug = new Map();
  responses.forEach((result, batchIndex) => {
    const batch = batches[batchIndex];
    if (result.status !== "fulfilled") {
      console.warn("Jellyfin-Prüfung der Filmreihe fehlgeschlagen:", result.reason);
      batch.forEach((item) => libraryStatusBySlug.set(item.slug, "unavailable"));
      return;
    }
    const response = result.value;
    batch.forEach((item) => libraryStatusBySlug.set(
      item.slug, movieCollectionJellyfinResponseStatus(response, item),
    ));
  });
  const resolvable = [];
  collection.parts.forEach((part) => {
    const status = libraryStatusBySlug.get(part.slug) || "unavailable";
    const queued = state.queuedSlugs.has(part.slug);
    const future = collectionReleaseIsFuture(part);
    applyMovieJellyfinStatus(part.slug, status);
    updateCollectionRecord(part.slug, {
      libraryStatus: status,
      providerStatus: queued || status === "owned"
        ? "skipped"
        : future
          ? "future"
          : collectionLibraryAllowsDownload(status) ? "waiting" : "blocked",
      queueStatus: queued ? "queued" : "idle",
      selected: false,
    });
    if (!queued && collectionLibraryAllowsDownload(status) && !future) resolvable.push(part);
  });
  renderMovieCollection();
  return resolvable;
}

function movieCollectionJellyfinRequest(part) {
  return {
    slug: part.slug,
    title: part.title,
    year: part.year || "",
    tmdb_id: part.tmdb_id,
    media_type: "movie",
  };
}

function movieCollectionJellyfinResponseStatus(response, part) {
  if (response.statuses?.[part.slug]) return response.statuses[part.slug];
  if (Object.hasOwn(response.matches || {}, part.slug)) {
    return response.matches[part.slug] ? "owned" : "missing";
  }
  return response.configured === false ? "unconfigured" : "unavailable";
}

async function retryMovieCollectionJellyfinPart(part) {
  const requestId = state.movieCollections.requestSeq;
  const current = collectionAvailabilityRecord(part);
  updateCollectionRecord(part.slug, {
    libraryStatus: "checking", providerStatus: "blocked", selected: false, message: "",
  });
  renderMovieCollection();
  let status;
  try {
    const response = await api.jellyfinMatches([movieCollectionJellyfinRequest(part)]);
    status = movieCollectionJellyfinResponseStatus(response, part);
  } catch (error) {
    status = [401, 403].includes(Number(error?.status)) ? "blocked" : "unavailable";
  }
  if (requestId !== state.movieCollections.requestSeq) return;
  applyMovieJellyfinStatus(part.slug, status);
  if (status === "owned") {
    updateCollectionRecord(part.slug, {
      libraryStatus: status, providerStatus: "skipped", queueStatus: "idle", selected: false,
    });
    renderMovieCollection();
    return;
  }
  if (!collectionLibraryAllowsDownload(status)) {
    updateCollectionRecord(part.slug, {
      libraryStatus: status, providerStatus: "blocked", queueStatus: "idle", selected: false,
    });
    renderMovieCollection();
    return;
  }
  const providerKnown = current.providerCount > 0 || Boolean(state.fp.moviesCache[part.slug]);
  updateCollectionRecord(part.slug, {
    libraryStatus: status,
    providerStatus: providerKnown ? "available" : "waiting",
    queueStatus: "idle",
    selected: providerKnown,
  });
  renderMovieCollection();
  if (!providerKnown) await resolveMovieCollectionPart(part, requestId);
  if (requestId !== state.movieCollections.requestSeq) return;
  if (collectionSelectable(collectionAvailabilityRecord(part))) {
    await queueCollectionMovies([part.slug]);
  }
}

async function retryMovieCollectionPart(part) {
  const requestId = state.movieCollections.requestSeq;
  await resolveMovieCollectionPart(part, requestId);
}

async function openMovieCollection(collectionId, trigger = null) {
  const requestId = ++state.movieCollections.requestSeq;
  state.movieCollections.activeId = Number(collectionId);
  state.movieCollections.collection = null;
  state.movieCollections.availability = new Map();
  state.movieCollections.resolving = false;
  state.movieCollections.queuePending = false;
  document.getElementById("movie-collection-title").textContent = "Filmreihe wird geladen";
  document.getElementById("movie-collection-description").textContent = "";
  document.getElementById("movie-collection-status").textContent = "TMDB-Daten werden geladen …";
  document.getElementById("movie-collection-progress").textContent = "";
  document.getElementById("movie-collection-films").replaceChildren();
  document.getElementById("movie-collection-counts").replaceChildren();
  document.getElementById("movie-collection-select-all").disabled = true;
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
      state.movieCollections.availability.set(part.slug, {
        libraryStatus: "checking",
        providerStatus: "waiting",
        queueStatus: state.queuedSlugs.has(part.slug) ? "queued" : "idle",
        selected: false,
        providerCount: 0,
        message: "",
      });
      state.fp.metadataCache[part.slug] = { ...part, details_loaded: false };
    });
    renderMovieCollection();
    const resolvable = await checkMovieCollectionJellyfin(collection, requestId);
    if (requestId !== state.movieCollections.requestSeq) return;
    void resolveMovieCollectionParts(resolvable, requestId);
  } catch (error) {
    if (requestId !== state.movieCollections.requestSeq) return;
    document.getElementById("movie-collection-title").textContent = "Filmreihe nicht verfügbar";
    document.getElementById("movie-collection-status").textContent = error?.message || "TMDB konnte die Reihe nicht laden.";
  }
}

async function queueCollectionMovies(slugs) {
  const available = slugs.filter(
    (slug) => collectionSelectable(collectionAvailabilityRecord({ slug })),
  );
  if (!available.length) return;
  state.movieCollections.queuePending = true;
  available.forEach((slug) => updateCollectionRecord(slug, {
    queueStatus: "adding", message: "",
  }));
  renderMovieCollection();
  try {
    const response = await api.queueAdd(available, {}, "collection");
    refreshQueueUiAfterChange(response);
    const queued = state.queuedSlugs;
    available.forEach((slug) => {
      const message = response.skipped_details?.[slug] || "Der Film wurde nicht eingeplant.";
      const normalized = message.toLocaleLowerCase("de-DE");
      if (queued.has(slug) || normalized.includes("bereits eingeplant")) {
        updateCollectionRecord(slug, { queueStatus: "queued", selected: false, message: "" });
      } else if (normalized.includes("in jellyfin vorhanden")) {
        applyMovieJellyfinStatus(slug, "owned", true);
        updateCollectionRecord(slug, {
          libraryStatus: "owned", providerStatus: "skipped",
          queueStatus: "idle", selected: false, message: "",
        });
      } else if (normalized.includes("kein hoster verfügbar")) {
        updateCollectionRecord(slug, {
          providerStatus: "unavailable", queueStatus: "idle",
          selected: false, message,
        });
      } else if (normalized.includes("jellyfin") && (
        normalized.includes("nicht erreichbar")
        || normalized.includes("sicherheitsprüfung")
        || normalized.includes("statusanfrage blockiert")
      )) {
        const status = normalized.includes("blockiert") ? "blocked" : "unavailable";
        applyMovieJellyfinStatus(slug, status);
        updateCollectionRecord(slug, {
          libraryStatus: status, providerStatus: "blocked",
          queueStatus: "idle", selected: false, message,
        });
      } else {
        updateCollectionRecord(slug, {
          queueStatus: "skipped", selected: false, message,
        });
      }
    });
  } catch (error) {
    available.forEach((slug) => updateCollectionRecord(slug, {
      queueStatus: "error",
      selected: true,
      message: error?.message || "Queue-Anfrage fehlgeschlagen",
    }));
  }
  state.movieCollections.queuePending = false;
  renderMovieCollection();
}

document.getElementById("movie-collection-select-all")?.addEventListener("click", () => {
  const collection = state.movieCollections.collection;
  if (!collection) return;
  const selectable = collection.parts.filter(
    (part) => collectionSelectable(collectionAvailabilityRecord(part)),
  );
  const shouldSelect = selectable.some(
    (part) => !collectionAvailabilityRecord(part).selected,
  );
  selectable.forEach((part) => updateCollectionRecord(part.slug, {
    selected: shouldSelect,
    ...(shouldSelect ? { queueStatus: "idle", message: "" } : {}),
  }));
  renderMovieCollection();
});

document.getElementById("movie-collection-download-all")?.addEventListener("click", () => {
  const collection = state.movieCollections.collection;
  if (!collection) return;
  void queueCollectionMovies(collection.parts
    .filter((part) => collectionAvailabilityRecord(part).selected)
    .map((part) => part.slug));
});
