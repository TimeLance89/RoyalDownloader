import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

/** Collection details own availability work; queue mutations belong to the session. */
export function createMovieCollections(root, {
  client = api, getMovieCache, getMetadataCache, getQueuedSlugs, coverCandidates, coverUrl,
  mediaCardInitials, openMediaModal, selectFpRow, applyMovieJellyfinStatus, refreshQueueUiAfterChange,
}) {
  const document = root.ownerDocument;
  const byId = id => root.querySelector(`#${id}`);
  const data = { activeId: null, requestSeq: 0, collection: null, availability: new Map(), resolving: false, queuePending: false };
  const callbacks = new WeakMap();
  let session = createScope(), detail = null, listening = false;
  function bind(node, type, callback) {
    const handlers = callbacks.get(node) || {};
    handlers[type] = callback; callbacks.set(node, handlers);
  }
  function dispatch(event) {
    for (let node = event.target; node && node !== document; node = node.parentElement) {
      const callback = callbacks.get(node)?.[event.type];
      if (callback) { callback(event); return; }
    }
  }
  function close() {
    detail?.dispose(); detail = null; data.requestSeq++;
    data.resolving = false; data.queuePending = false;
  }
  function loadMovie(part, signal) {
    const query = Number(part.tmdb_id) > 0 ? `?${new URLSearchParams({ tmdb_id: String(part.tmdb_id) })}` : "";
    return client.get(`/api/movie/${encodeURIComponent(part.slug)}${query}`, { signal });
  }
  function checkJellyfin(items, signal) {
    return client.post("/api/jellyfin/matches", { items }, { signal, timeoutMs: 15_000,
      timeoutMessage: "Die Jellyfin-Statusprüfung hat nicht rechtzeitig geantwortet." });
  }
  const COLLECTION_RESOLVE_WORKERS = 2;

  function collectionArtwork(image, url, eager = false) {
    const candidates = coverCandidates(url);
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
    bind(button, "click", () => openMovieCollection(collection.collection_id, card));
    return card;
  }

  function collectionAvailabilityRecord(part) {
    return data.availability.get(part.slug) || {
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
    data.availability.set(slug, { ...current, ...changes });
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
    bind(checkbox, "change", () => setCollectionSelected(part.slug, checkbox.checked));
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
    bind(open, "click", () => selectFpRow(part.slug, part));
    const download = document.createElement("button");
    download.type = "button";
    download.className = "is-primary";
    download.textContent = record.queueStatus === "queued" ? "Eingeplant" : "Einzeln laden";
    download.disabled = !collectionSelectable(record) || data.queuePending;
    if (record.providerStatus === "blocked") {
      download.textContent = "Prüfen & laden";
      download.disabled = record.libraryStatus === "checking" || data.queuePending;
      bind(download, "click", () => void retryMovieCollectionJellyfinPart(part));
    } else if (["unavailable", "error"].includes(record.providerStatus)) {
      download.textContent = "Erneut prüfen";
      download.disabled = data.resolving;
      bind(download, "click", () => void retryMovieCollectionPart(part));
    } else bind(download, "click", () => queueCollectionMovies([part.slug]));
    actions.append(open, download);
    card.append(selection, order, poster, copy, actions);
    return card;
  }

  function renderMovieCollection() {
    const collection = data.collection;
    const list = byId("movie-collection-films");
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
    data.resolving = libraryPending > 0
      || providerCandidates.some((record) => ["waiting", "checking"].includes(record.providerStatus));
    byId("movie-collection-status").textContent = libraryPending
      ? `Jellyfin-Status für ${collection.parts.length} Filme wird geprüft`
      : libraryUncertain
        ? `${libraryUncertain} ${libraryUncertain === 1 ? "Jellyfin-Prüfung ist" : "Jellyfin-Prüfungen sind"} noch offen`
      : data.resolving
        ? `${providerChecked} von ${providerCandidates.length} Anbieterprüfungen abgeschlossen`
        : `${collection.parts.length} Filme vollständig geprüft`;
    byId("movie-collection-progress").textContent = libraryPending
      ? "Vorhandene Filme werden nicht erneut bei den Anbietern gesucht."
      : libraryUncertain
        ? "Betroffene Filme bleiben gesperrt, bis Jellyfin ihren Bestand sicher bestätigt hat."
      : data.resolving
        ? "Gefundene Filme werden sofort auswählbar; Fehler bleiben auf den einzelnen Titel begrenzt."
        : "Nur ausgewählte, verfügbare und noch nicht vorhandene Filme gehen in die Queue.";

    const counts = byId("movie-collection-counts");
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

    const selectAll = byId("movie-collection-select-all");
    const everyAvailableSelected = available > 0 && available === selected;
    selectAll.disabled = available === 0 || data.queuePending;
    selectAll.textContent = everyAvailableSelected ? "Auswahl aufheben" : "Verfügbare auswählen";
    const allButton = byId("movie-collection-download-all");
    allButton.disabled = selected === 0 || data.queuePending;
    allButton.textContent = data.queuePending
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
      const movie = await loadMovie(part, detail.signal);
      if (requestId !== data.requestSeq) return;
      getMovieCache()[part.slug] = movie;
      getMetadataCache()[part.slug] = { ...part, ...movie };
      updateCollectionRecord(part.slug, {
        providerStatus: "available",
        providerCount: Math.max(1, Number(movie.source_count || movie.provider_count || 1)),
        selected: true,
      });
    } catch (error) {
      if (requestId !== data.requestSeq) return;
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
      while (cursor < parts.length && requestId === data.requestSeq) {
        const part = parts[cursor];
        cursor += 1;
        await resolveMovieCollectionPart(part, requestId);
      }
    }
    await Promise.all(Array.from(
      { length: Math.min(COLLECTION_RESOLVE_WORKERS, parts.length) },
      () => worker(),
    ));
    if (requestId !== data.requestSeq) return;
    renderMovieCollection();
  }

  async function checkMovieCollectionJellyfin(collection, requestId) {
    const requests = collection.parts.map(movieCollectionJellyfinRequest);
    const batches = [];
    for (let index = 0; index < requests.length; index += 100) {
      batches.push(requests.slice(index, index + 100));
    }
    const responses = await Promise.allSettled(
      batches.map((batch) => checkJellyfin(batch, detail.signal)),
    );
    if (requestId !== data.requestSeq) return [];
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
      const queued = getQueuedSlugs().has(part.slug);
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
    const requestId = data.requestSeq;
    const current = collectionAvailabilityRecord(part);
    updateCollectionRecord(part.slug, {
      libraryStatus: "checking", providerStatus: "blocked", selected: false, message: "",
    });
    renderMovieCollection();
    let status;
    try {
      const response = await checkJellyfin([movieCollectionJellyfinRequest(part)], detail.signal);
      status = movieCollectionJellyfinResponseStatus(response, part);
    } catch (error) {
      status = [401, 403].includes(Number(error?.status)) ? "blocked" : "unavailable";
    }
    if (requestId !== data.requestSeq) return;
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
    const providerKnown = current.providerCount > 0 || Boolean(getMovieCache()[part.slug]);
    updateCollectionRecord(part.slug, {
      libraryStatus: status,
      providerStatus: providerKnown ? "available" : "waiting",
      queueStatus: "idle",
      selected: providerKnown,
    });
    renderMovieCollection();
    if (!providerKnown) await resolveMovieCollectionPart(part, requestId);
    if (requestId !== data.requestSeq) return;
    if (collectionSelectable(collectionAvailabilityRecord(part))) {
      await queueCollectionMovies([part.slug]);
    }
  }

  async function retryMovieCollectionPart(part) {
    const requestId = data.requestSeq;
    await resolveMovieCollectionPart(part, requestId);
  }

  async function openMovieCollection(collectionId, trigger = null) {
    if (!session.active) return;
    close();
    detail = createScope();
    const requestId = data.requestSeq;
    data.activeId = Number(collectionId);
    data.collection = null;
    data.availability = new Map();
    data.resolving = false;
    data.queuePending = false;
    byId("movie-collection-title").textContent = "Filmreihe wird geladen";
    byId("movie-collection-description").textContent = "";
    byId("movie-collection-status").textContent = "TMDB-Daten werden geladen …";
    byId("movie-collection-progress").textContent = "";
    byId("movie-collection-films").replaceChildren();
    byId("movie-collection-counts").replaceChildren();
    byId("movie-collection-select-all").disabled = true;
    byId("movie-collection-download-all").disabled = true;
    openMediaModal("movie-collection-modal", trigger);
    try {
      const response = await client.get(`/api/movie-collections/${encodeURIComponent(collectionId)}`, { signal: detail.signal });
      if (requestId !== data.requestSeq) return;
      const collection = response.collection;
      data.collection = collection;
      byId("movie-collection-title").textContent = collection.title;
      byId("movie-collection-description").textContent = collection.description
        || `${collection.part_count} Filme in Veröffentlichungsreihenfolge.`;
      const cover = byId("movie-collection-cover");
      cover.alt = `Cover von ${collection.title}`;
      collectionArtwork(cover, collection.cover_url, true);
      const hero = byId("movie-collection-hero");
      const backdrop = coverUrl(collection.backdrop_url || "");
      hero.style.setProperty("--collection-backdrop", backdrop ? `url("${backdrop.replace(/"/g, "%22")}")` : "none");
      collection.parts.forEach((part) => {
        data.availability.set(part.slug, {
          libraryStatus: "checking",
          providerStatus: "waiting",
          queueStatus: getQueuedSlugs().has(part.slug) ? "queued" : "idle",
          selected: false,
          providerCount: 0,
          message: "",
        });
        getMetadataCache()[part.slug] = { ...part, details_loaded: false };
      });
      renderMovieCollection();
      const resolvable = await checkMovieCollectionJellyfin(collection, requestId);
      if (requestId !== data.requestSeq) return;
      void resolveMovieCollectionParts(resolvable, requestId);
    } catch (error) {
      if (requestId !== data.requestSeq) return;
      byId("movie-collection-title").textContent = "Filmreihe nicht verfügbar";
      byId("movie-collection-status").textContent = error?.message || "TMDB konnte die Reihe nicht laden.";
    }
  }

  async function queueCollectionMovies(slugs) {
    if (!session.active || !detail?.active || data.queuePending) return;
    const requestId = data.requestSeq;
    const owner = session;
    const available = slugs.filter(
      (slug) => collectionSelectable(collectionAvailabilityRecord({ slug })),
    );
    if (!available.length) return;
    data.queuePending = true;
    available.forEach((slug) => updateCollectionRecord(slug, {
      queueStatus: "adding", message: "",
    }));
    renderMovieCollection();
    try {
      const response = await client.post("/api/queue/add", { slugs: available, preferences: {}, source: "collection" }, { signal: owner.signal });
      if (!owner.active) return;
      refreshQueueUiAfterChange(response);
      if (requestId !== data.requestSeq) return;
      const queued = getQueuedSlugs();
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
      if (!owner.active || requestId !== data.requestSeq) return;
      available.forEach((slug) => updateCollectionRecord(slug, {
        queueStatus: "error",
        selected: true,
        message: error?.message || "Queue-Anfrage fehlgeschlagen",
      }));
    }
    data.queuePending = false;
    renderMovieCollection();
  }

  function mount() {
    if (listening) return;
    if (!session.active) session = createScope();
    listening = true;
    session.listen(document, "click", dispatch);
    session.listen(document, "change", dispatch);
    session.listen(byId("movie-collection-select-all"), "click", () => {
      const collection = data.collection;
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

    session.listen(byId("movie-collection-download-all"), "click", () => {
      const collection = data.collection;
      if (!collection) return;
      void queueCollectionMovies(collection.parts
        .filter((part) => collectionAvailabilityRecord(part).selected)
        .map((part) => part.slug));
    });
  }
  function unmount() { close(); session.dispose(); listening = false; }
  return { get: () => data, open: openMovieCollection, createCard: createMovieCollectionSearchCard, close, mount, unmount };
}
