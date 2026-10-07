import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { creditKey, defaultFilters, departments, filmCandidate, filterCredits, highlights, isUpcoming } from "./model.js";
export { filterCredits } from "./model.js";

/** Portrait directory and filmography; queue writes remain in the collection feature. */
export function createPeople(root, { client = api, coverUrl, openMovie, openSeries, openFilms, getQueuedSlugs = () => new Set() }) {
  const document = root.ownerDocument;
  let scope = null, request = null, version = 0;
  let listing = null, person = null, query = "", page = 1;
  let retryId = null;
  const filters = defaultFilters(), selected = new Set(), statuses = new Map(), recent = new Map();
  let libraryOwner = null, libraryPending = false, directoryRole = "all", visibleLimit = 48;
  const byId = id => root.querySelector(`#${id}`);
  const directory = byId("people-directory"), profile = byId("people-profile");
  function node(tag, className, text = "") {
    const el = document.createElement(tag); el.className = className; el.textContent = text; return el;
  }
  function button(text, action) {
    const el = node("button", "people-button", text); el.type = "button"; el.dataset.peopleAction = action; return el;
  }
  function image(url, label, className) {
    const frame = node("span", className, label.trim().split(/\s+/).slice(0, 2).map(word => word[0]).join(""));
    if (url) {
      const img = node("img", ""); img.src = coverUrl(url); img.alt = "";
      img.loading = "lazy"; img.decoding = "async";
      img.addEventListener("error", () => img.remove(), { once: true }); frame.append(img);
    }
    return frame;
  }
  function begin() {
    if (libraryPending) byId("people-library-status").textContent = "Bestandsprüfung unterbrochen. Du kannst sie erneut starten.";
    libraryOwner?.dispose(); libraryPending = false;
    request?.dispose(); request = createScope(); const id = ++version;
    return { owner: request, current: () => scope?.active && request?.active && id === version };
  }
  function status(text, error = false) {
    const el = byId("people-status"); el.textContent = text; el.classList.toggle("people-error", error);
    el.parentElement.hidden = !text;
    byId("people-retry").hidden = !error;
  }
  function renderDirectory() {
    root.querySelector(".people-heading").hidden = false;
    directory.hidden = false; profile.hidden = true;
    const grid = byId("people-results"); grid.replaceChildren();
    const results = (listing?.results || []).filter(item => directoryRole === "all" || item.department === directoryRole);
    byId("people-directory-count").textContent = `${results.length} Personen auf dieser Seite`;
    for (const item of results) {
      const card = button("", "person"); card.className = "people-card"; card.dataset.personId = item.id;
      card.setAttribute("aria-label", `${item.name}: Filmografie öffnen`);
      card.append(image(item.profile_url, item.name, "people-portrait"), node("strong", "people-name", item.name),
        node("span", "people-department", departments[item.department] || item.department || "Film & Fernsehen"),
        node("span", "people-known", (item.known_for || []).filter(Boolean).slice(0, 3).join(" · ")));
      grid.append(card);
    }
    if (!results.length) grid.append(node("p", "people-empty", "Keine Personen für diesen Bereich auf der aktuellen Seite. Ändere den Filter oder blättere weiter."));
    const history = byId("people-recent"); history.replaceChildren(); history.hidden = !recent.size;
    if (recent.size) {
      history.append(node("span", "", "Zuletzt angesehen"));
      for (const { person: item } of [...recent.values()].reverse()) {
        const link = button(item.name, "person"); link.dataset.personId = item.id; history.append(link);
      }
    }
    byId("people-page").textContent = `Seite ${page} von ${listing?.total_pages || 1}`;
    byId("people-prev").disabled = page <= 1;
    byId("people-next").disabled = page >= (listing?.total_pages || 1);
  }
  async function browse() {
    retryId = null;
    person = null; selected.clear(); statuses.clear(); renderDirectory();
    const work = begin(); status("Personen werden geladen …");
    byId("people-results").setAttribute("aria-busy", "true");
    byId("people-prev").disabled = true; byId("people-next").disabled = true;
    try {
      const response = await client.get(`/api/people?${new URLSearchParams({ query, page: String(page) })}`, { signal: work.owner.signal });
      if (!work.current()) return;
      listing = response; renderDirectory();
      status(response.results.length ? (query ? `Personen für „${query}“` : "Aktuell beliebte Personen auf TMDB") : "Keine Personen gefunden. Versuche einen anderen Namen.");
    } catch (error) { if (work.current()) status(error.message, true); }
    finally { if (work.current()) byId("people-results").removeAttribute("aria-busy"); }
  }
  function renderWorks() {
    const works = filterCredits(person.credits, filters, statuses);
    const activeFilters = [filters.role, filters.year, filters.release, filters.library].filter(value => value !== "all").length;
    byId("people-active-filters").textContent = activeFilters ? `${activeFilters} aktiv` : "";
    const queued = getQueuedSlugs();
    const focused = document.activeElement?.dataset?.creditSelect;
    const grid = byId("people-works"); grid.replaceChildren();
    byId("people-work-count").textContent = `${works.length} von ${person.credits.length} Werken`;
    for (const item of works.slice(0, visibleLimit)) {
      const entry = node("article", "people-work-entry");
      const card = button("", "work"); card.className = "people-work";
      card.dataset.tmdbId = item.tmdb_id; card.dataset.mediaType = item.media_type;
      card.setAttribute("aria-label", `${item.title}: ${item.media_type === "tv" ? "Episoden" : "Film"} öffnen`);
      const copy = node("span", "people-work-copy");
      copy.append(node("span", "people-work-meta", `${item.media_type === "tv" ? "SERIE" : "FILM"} · ${item.year || "Ohne Datum"}`),
        node("strong", "", item.title), node("span", "people-work-role", (item.roles || []).join(" · ") || "Mitwirkung"),
        node("span", "people-work-action", item.media_type === "tv" ? "Episoden ansehen ↗" : "Film ansehen ↗"));
      card.append(image(item.cover_url, item.title, "people-work-poster"), copy); entry.append(card);
      const footer = node("div", "people-work-footer");
      const library = statuses.get(creditKey(item));
      const label = queued.has(item.slug) && item.media_type === "movie" ? "In der Queue" : isUpcoming(item) ? "Angekündigt" : ({ owned: item.media_type === "tv" ? "Serie in Jellyfin" : "In Jellyfin", missing: "Fehlt in Jellyfin", unconfigured: "Jellyfin nicht eingerichtet", unavailable: "Bestand unklar", blocked: "Bestand unklar", ambiguous: "Zuordnung unklar" })[library] || "Bestand nicht geprüft";
      footer.append(node("span", `people-work-status ${library === "owned" ? "is-owned" : ""}`, label));
      if (Number(item.rating) > 0 && Number(item.vote_count) >= 10) footer.append(node("span", "people-rating", `★ ${Number(item.rating).toLocaleString(document.documentElement.lang || "de", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`));
      if (item.media_type === "movie") {
        const choice = node("label", "people-work-select", "Vormerken");
        const input = document.createElement("input"); input.type = "checkbox"; input.dataset.creditSelect = creditKey(item);
        input.checked = selected.has(creditKey(item)); input.disabled = !filmCandidate(item, statuses, queued);
        input.setAttribute("aria-label", `${item.title} für die Filmauswahl vormerken`); choice.prepend(input); footer.append(choice);
      }
      entry.append(footer); grid.append(entry);
    }
    if (!works.length) grid.append(node("p", "people-empty", filters.library !== "all" && !statuses.size ? "Prüfe zuerst den Jellyfin-Bestand oder wähle alle Bestände." : "Keine Werke für diese Filter. Setze die Filter zurück oder suche einen anderen Titel."));
    const films = works.filter(item => filmCandidate(item, statuses, queued));
    const batch = byId("people-films"); batch.disabled = !films.length;
    batch.textContent = `${films.length} Filme prüfen & auswählen`;
    byId("people-batch-note").textContent = "Die Anbieterprüfung folgt vor dem Download. Serien öffnest du einzeln, um die gewünschten Episoden auszuwählen.";
    const chosen = person.credits.filter(item => selected.has(creditKey(item)) && filmCandidate(item, statuses, queued));
    byId("people-selection").hidden = !chosen.length;
    byId("people-selection-count").textContent = `${chosen.length} Filme vorgemerkt`;
    const hidden = chosen.filter(item => !works.some(work => creditKey(work) === creditKey(item))).length;
    byId("people-selection-note").textContent = hidden ? `${hidden} davon sind durch die Filter ausgeblendet. Die Auswahl bleibt erhalten.` : "Verfügbarkeit, Sprache und Bestand werden vor dem Download erneut geprüft.";
    byId("people-select-visible").disabled = !films.length;
    byId("people-show-more").hidden = works.length <= visibleLimit;
    byId("people-show-more").textContent = `Weitere ${Math.min(48, works.length - visibleLimit)} Werke anzeigen`;
    if (focused) [...grid.querySelectorAll("[data-credit-select]")].find(input => input.dataset.creditSelect === focused)?.focus();
  }
  function syncFilters() {
    for (const key of Object.keys(filters)) byId(`people-filter-${key}`).value = filters[key];
  }
  function profileOptions() {
    const year = byId("people-filter-year"); year.replaceChildren(new Option("Alle Jahre", "all"));
    [...new Set(person.credits.map(item => item.year).filter(value => /^\d{4}$/.test(value)))].sort().reverse().forEach(value => year.append(new Option(value, value)));
    const role = byId("people-filter-role"); role.replaceChildren(new Option("Alle Mitwirkungen", "all"));
    [...new Set(person.credits.flatMap(item => item.departments || []))].sort().forEach(value => role.append(new Option(departments[value] || value, value === "Acting" ? "acting" : value)));
    if (![...role.options].some(option => option.value === filters.role)) filters.role = "all";
  }
  async function checkLibrary() {
    if (!person || libraryPending) return;
    libraryOwner?.dispose(); const owner = createScope(); libraryOwner = owner; libraryPending = true;
    const identity = person.id, credits = person.credits;
    const control = byId("people-library-check"); control.disabled = true;
    const progress = byId("people-library-status"); let checked = 0;
    for (let offset = 0; offset < credits.length && owner.active; offset += 100) {
      const batch = credits.slice(offset, offset + 100);
      progress.textContent = `${checked} von ${credits.length} Werken geprüft …`;
      try {
        const response = await client.post("/api/jellyfin/matches", { items: batch.map(item => ({
          slug: creditKey(item), title: item.title, tmdb_id: item.tmdb_id, year: item.year,
          media_type: item.media_type === "tv" ? "series" : "movie",
        })) }, { signal: owner.signal, timeoutMs: 15_000 });
        if (!owner.active || person?.id !== identity) return;
        for (const item of batch) {
          const key = creditKey(item);
          const value = response.statuses?.[key] || (Object.hasOwn(response.matches || {}, key) ? (response.matches[key] ? "owned" : "missing") : response.configured === false ? "unconfigured" : "unavailable");
          statuses.set(key, value); if (value === "owned") selected.delete(key);
        }
      } catch (error) {
        if (!owner.active || person?.id !== identity) return;
        batch.forEach(item => statuses.set(creditKey(item), [401, 403].includes(error.status) ? "blocked" : "unavailable"));
      }
      checked += batch.length; renderWorks();
    }
    if (!owner.active) return;
    libraryPending = false; control.disabled = false;
    const unknown = [...statuses.values()].filter(value => ["unavailable", "blocked", "ambiguous"].includes(value)).length;
    const unconfigured = credits.length && [...statuses.values()].every(value => value === "unconfigured");
    progress.textContent = unconfigured ? "Jellyfin ist nicht eingerichtet. Du kannst die Filmauswahl trotzdem bei den Anbietern prüfen."
      : unknown ? `${unknown} Bestände sind noch unklar. Erneut prüfen oder die Werke einzeln öffnen.`
        : `${checked} Bestände geprüft. Bei Serien kann weiterhin eine Episode fehlen.`;
    control.textContent = "Bestand erneut prüfen";
  }
  function renderProfile() {
    root.querySelector(".people-heading").hidden = true;
    directory.hidden = true; profile.hidden = false;
    const hero = byId("people-profile-hero"); hero.replaceChildren();
    const copy = node("div", "people-profile-copy");
    const facts = [departments[person.department] || person.department, person.birthplace].filter(Boolean);
    copy.append(node("p", "people-profile-label", "Personenprofil"), node("h2", "people-profile-name", person.name), node("p", "people-facts", facts.join(" · ")));
    if (person.birthday) {
      const date = value => new Date(`${value}T12:00:00`).toLocaleDateString(document.documentElement.lang || "de", { day: "numeric", month: "long", year: "numeric" });
      copy.append(node("p", "people-facts", `Geboren ${date(person.birthday)}${person.deathday ? ` · Gestorben ${date(person.deathday)}` : ""}`));
    }
    const excerpt = node("p", "people-bio-excerpt", person.biography || "Zu dieser Person liegt noch keine Biografie vor. Ihre Filme und Serien findest du darunter."); copy.append(excerpt);
    const bio = node("details", "people-biography");
    bio.append(node("summary", "", "Vollständige Biografie lesen"), node("p", "", person.biography || "Für diese Person liegt noch keine Biografie vor.")); bio.hidden = !person.biography; copy.append(bio);
    const stats = node("div", "people-profile-stats");
    for (const [type, label] of [["movie", "Filme"], ["tv", "Serien"]]) {
      const stat = button("", "type"); stat.className = "people-stat"; stat.dataset.mediaType = type; stat.setAttribute("aria-label", `Alle ${label} anzeigen`);
      stat.append(node("strong", "", String(person.credits.filter(item => item.media_type === type).length)), node("span", "", label)); stats.append(stat);
    }
    copy.append(stats);
    const factsPanel = node("aside", "people-person-facts"); factsPanel.setAttribute("aria-label", "Zur Person");
    factsPanel.append(node("h3", "", "Zur Person"));
    const dates = person.credits.filter(item => !isUpcoming(item)).map(item => item.year).filter(value => /^\d{4}$/.test(value)).sort();
    if (dates.length) factsPanel.append(node("span", "people-fact-label", "Werke aus den Jahren"), node("p", "", dates[0] === dates.at(-1) ? dates[0] : `${dates[0]}–${dates.at(-1)}`));
    const aliases = (person.also_known_as || []).filter(name => name !== person.name).slice(0, 6);
    if (aliases.length) factsPanel.append(node("span", "people-fact-label", "Auch bekannt als"), node("p", "people-aliases", aliases.join(", ")));
    const link = node("a", "people-tmdb-link", "Profil auf TMDB öffnen"); link.href = `https://www.themoviedb.org/person/${Number(person.id)}`; link.target = "_blank"; link.rel = "noopener noreferrer"; factsPanel.append(link);
    hero.append(image(person.profile_url, person.name, "people-profile-portrait"), copy, factsPanel);
    const picks = byId("people-highlights"); picks.replaceChildren();
    for (const item of highlights(person.credits)) {
      const card = button("", "work"); card.className = "people-highlight"; card.dataset.tmdbId = item.tmdb_id; card.dataset.mediaType = item.media_type;
      card.append(image(item.backdrop_url || item.cover_url, item.title, "people-highlight-art"), node("strong", "", item.title), node("span", "people-facts", `${item.media_type === "tv" ? "Serie" : "Film"} · ${item.year || "Ohne Datum"}`)); picks.append(card);
    }
    byId("people-highlights-section").hidden = !picks.childElementCount;
    byId("people-library-check").disabled = libraryPending || !person.credits.length;
    renderWorks();
  }
  async function open(id) {
    if (!scope?.active) return;
    retryId = id;
    const returning = person?.id === id;
    const work = begin(); status("Filmografie wird geladen …");
    try {
      const cached = recent.get(id);
      const response = cached && Date.now() - cached.fetchedAt < 300_000 ? { person: cached.person }
        : await client.get(`/api/people/${id}`, { signal: work.owner.signal });
      if (!work.current()) return;
      person = response.person;
      const fetchedAt = response.person === cached?.person ? cached.fetchedAt : Date.now();
      recent.delete(id); recent.set(id, { person, fetchedAt }); if (recent.size > 8) recent.delete(recent.keys().next().value);
      if (!returning) {
        selected.clear(); statuses.clear(); visibleLimit = 48;
        Object.assign(filters, defaultFilters(), { role: person.department === "Acting" ? "acting" : "all" });
      }
      profileOptions(); syncFilters();
      if (!returning) {
        byId("people-library-status").textContent = "Prüfe deinen Jellyfin-Bestand, um vorhandene und fehlende Werke zu unterscheiden.";
        byId("people-library-check").textContent = "Jellyfin-Bestand prüfen";
      }
      renderProfile(); status("");
      byId("people-back").focus(); root.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch (error) { if (work.current()) status(error.message, true); }
  }
  function click(event) {
    const target = event.target.closest("[data-people-action]"); if (!target || !root.contains(target)) return;
    switch (target.dataset.peopleAction) {
      case "person": void open(Number(target.dataset.personId)); break;
      case "back": begin(); person = null; renderDirectory(); status(query ? `Personen für „${query}“` : "Aktuell beliebte Personen auf TMDB"); if (!listing) void browse(); byId("people-search").focus(); break;
      case "prev": page--; void browse(); break;
      case "next": page++; void browse(); break;
      case "retry": if (retryId) void open(retryId); else void browse(); break;
      case "reset-search": query = ""; page = 1; byId("people-search").value = ""; void browse(); break;
      case "reset-filters": Object.assign(filters, defaultFilters(), { role: person.department === "Acting" ? "acting" : "all" }); visibleLimit = 48; syncFilters(); renderWorks(); break;
      case "type": Object.assign(filters, defaultFilters(), { type: target.dataset.mediaType, role: "all" }); visibleLimit = 48; syncFilters(); renderWorks(); byId("people-filter-type").focus(); break;
      case "library": void checkLibrary(); break;
      case "more": visibleLimit += 48; renderWorks(); break;
      case "select-visible": filterCredits(person.credits, filters, statuses).filter(item => filmCandidate(item, statuses, getQueuedSlugs())).forEach(item => selected.add(creditKey(item))); renderWorks(); break;
      case "clear-selection": selected.clear(); renderWorks(); break;
      case "selection":
      case "films": {
        const candidates = target.dataset.peopleAction === "selection" ? person.credits.filter(item => selected.has(creditKey(item))) : filterCredits(person.credits, filters, statuses);
        const parts = candidates.filter(item => filmCandidate(item, statuses, getQueuedSlugs()));
        if (!parts.length) { renderWorks(); break; }
        openFilms({ title: `${person.name} · Filmauswahl`, description: `${parts.length} vorgemerkte Filme. Vorhandene Titel werden ausgelassen; verfügbare Quellen und Sprachen werden geprüft.`, cover_url: person.profile_url, parts, part_count: parts.length }, target); break;
      }
      case "work": {
        const item = person.credits.find(item => String(item.tmdb_id) === target.dataset.tmdbId && item.media_type === target.dataset.mediaType);
        if (item?.media_type === "tv") openSeries({ ...item, sample_slug: `people-tmdb:${item.tmdb_id}`, base_slug: `people-tmdb:${item.tmdb_id}`, sources: [], metadata_source: "TMDB" });
        else if (item) openMovie(item.slug, { ...item, hosters: [], metadata_source: "TMDB" });
        break;
      }
    }
  }
  function mount() {
    if (scope?.active) return;
    scope = createScope(); scope.listen(root, "click", click);
    scope.listen(byId("people-search-form"), "submit", event => { event.preventDefault(); query = byId("people-search").value.trim(); page = 1; void browse(); });
    scope.listen(byId("people-directory-role"), "change", event => { directoryRole = event.target.value; renderDirectory(); });
    scope.listen(root, "change", event => {
      const key = event.target.dataset.creditSelect; if (!key) return;
      if (event.target.checked) selected.add(key); else selected.delete(key); renderWorks();
    });
    for (const key of Object.keys(filters)) scope.listen(byId(`people-filter-${key}`), key === "query" ? "input" : "change", event => { filters[key] = event.target.value; visibleLimit = 48; if (person) renderWorks(); });
    if (person) renderProfile(); else if (listing) renderDirectory(); else void browse();
  }
  function unmount() {
    if (libraryPending) byId("people-library-status").textContent = "Bestandsprüfung unterbrochen. Du kannst sie erneut starten.";
    scope?.dispose(); request?.dispose(); libraryOwner?.dispose(); libraryPending = false; version++;
  }
  return { mount, unmount, open };
}
