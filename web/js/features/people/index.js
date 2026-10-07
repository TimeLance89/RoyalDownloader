import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function filterCredits(credits, { type = "all", role = "acting", query = "", sort = "popular" } = {}) {
  const needle = query.trim().toLocaleLowerCase();
  return credits.filter(item => (type === "all" || item.media_type === type)
    && (role === "all" || (item.departments || []).includes("Acting"))
    && (!needle || `${item.title} ${item.original_title}`.toLocaleLowerCase().includes(needle)))
    .sort((a, b) => sort === "newest"
      ? String(b.release_date).localeCompare(String(a.release_date)) || a.title.localeCompare(b.title)
      : Number(b.popularity) - Number(a.popularity) || a.title.localeCompare(b.title));
}

/** Portrait directory and filmography; queue writes remain in the collection feature. */
export function createPeople(root, { client = api, coverUrl, openMovie, openSeries, openFilms }) {
  const document = root.ownerDocument;
  let scope = null, request = null, version = 0;
  let listing = null, person = null, query = "", page = 1;
  let retryId = null;
  const filters = { type: "all", role: "acting", query: "", sort: "popular" };
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
    for (const item of listing?.results || []) {
      const card = button("", "person"); card.className = "people-card"; card.dataset.personId = item.id;
      card.setAttribute("aria-label", `${item.name}: Filmografie öffnen`);
      card.append(image(item.profile_url, item.name, "people-portrait"), node("strong", "people-name", item.name),
        node("span", "people-known", item.known_for.filter(Boolean).slice(0, 3).join(" · ") || item.department));
      grid.append(card);
    }
    byId("people-page").textContent = `Seite ${page} von ${listing?.total_pages || 1}`;
    byId("people-prev").disabled = page <= 1;
    byId("people-next").disabled = page >= (listing?.total_pages || 1);
  }
  async function browse() {
    retryId = null;
    person = null; renderDirectory();
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
    const works = filterCredits(person.credits, filters);
    const grid = byId("people-works"); grid.replaceChildren();
    byId("people-work-count").textContent = `${works.length} ${works.length === 1 ? "Werk" : "Werke"}`;
    for (const item of works) {
      const card = button("", "work"); card.className = "people-work";
      card.dataset.tmdbId = item.tmdb_id; card.dataset.mediaType = item.media_type;
      card.setAttribute("aria-label", `${item.title}: ${item.media_type === "tv" ? "Episoden" : "Film"} öffnen`);
      const copy = node("span", "people-work-copy");
      copy.append(node("span", "people-work-meta", `${item.media_type === "tv" ? "SERIE" : "FILM"} · ${item.year || "Ohne Datum"}`),
        node("strong", "", item.title), node("span", "people-work-role", item.roles.join(" · ") || "Mitwirkung"),
        node("span", "people-work-action", item.media_type === "tv" ? "Episoden ansehen ↗" : "Film ansehen ↗"));
      card.append(image(item.cover_url, item.title, "people-work-poster"), copy); grid.append(card);
    }
    if (!works.length) grid.append(node("p", "people-empty", "Keine Werke für diese Filter."));
    const films = works.filter(item => item.media_type === "movie");
    const batch = byId("people-films"); batch.disabled = !films.length;
    batch.textContent = `${films.length} Filme prüfen & auswählen`;
    byId("people-batch-note").textContent = "Nur verfügbare, fehlende Filme herunterladen. Serien öffnen ihre Episodenauswahl.";
  }
  function renderProfile() {
    root.querySelector(".people-heading").hidden = true;
    directory.hidden = true; profile.hidden = false;
    const hero = byId("people-profile-hero"); hero.replaceChildren();
    const copy = node("div", "people-profile-copy");
    const facts = [person.department === "Acting" ? "Schauspiel" : person.department, person.birthplace].filter(Boolean);
    copy.append(node("p", "people-eyebrow", "PERSONEN / FILMOGRAFIE"), node("h2", "people-profile-name", person.name), node("p", "people-facts", facts.join(" · ")));
    if (person.birthday) {
      const date = value => new Date(`${value}T12:00:00`).toLocaleDateString(document.documentElement.lang || "de", { day: "numeric", month: "long", year: "numeric" });
      copy.append(node("p", "people-facts", `Geboren ${date(person.birthday)}${person.deathday ? ` · Gestorben ${date(person.deathday)}` : ""}`));
    }
    const bio = node("details", "people-biography");
    bio.append(node("summary", "", "Biografie"), node("p", "", person.biography || "Für diese Person liegt noch keine Biografie vor.")); copy.append(bio);
    const stats = node("div", "people-profile-stats");
    for (const [type, label] of [["movie", "Filme"], ["tv", "Serien"]]) {
      const stat = node("span", ""); stat.append(node("strong", "", String(person.credits.filter(item => item.media_type === type).length)), node("span", "", label)); stats.append(stat);
    }
    copy.append(stats); hero.append(image(person.profile_url, person.name, "people-profile-portrait"), copy);
    renderWorks();
  }
  async function open(id) {
    if (!scope?.active) return;
    retryId = id;
    const work = begin(); status("Filmografie wird geladen …");
    try {
      const response = await client.get(`/api/people/${id}`, { signal: work.owner.signal });
      if (!work.current()) return;
      person = response.person;
      Object.assign(filters, { type: "all", role: person.department === "Acting" ? "acting" : "all", query: "", sort: "popular" });
      for (const key of Object.keys(filters)) byId(`people-filter-${key}`).value = filters[key];
      renderProfile(); status("");
      byId("people-back").focus(); root.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch (error) { if (work.current()) status(error.message, true); }
  }
  function click(event) {
    const target = event.target.closest("[data-people-action]"); if (!target || !root.contains(target)) return;
    switch (target.dataset.peopleAction) {
      case "person": void open(Number(target.dataset.personId)); break;
      case "back": request?.dispose(); version++; person = null; renderDirectory(); status(query ? `Personen für „${query}“` : "Aktuell beliebte Personen auf TMDB"); byId("people-search").focus(); break;
      case "prev": page--; void browse(); break;
      case "next": page++; void browse(); break;
      case "retry": if (retryId) void open(retryId); else void browse(); break;
      case "films": {
        const parts = filterCredits(person.credits, filters).filter(item => item.media_type === "movie");
        openFilms({ title: `${person.name} · Filmografie`, description: "Filme aus der aktuellen Auswahl. Verfügbarkeit und Jellyfin-Bestand werden geprüft.", cover_url: person.profile_url, parts, part_count: parts.length }, target); break;
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
    for (const key of Object.keys(filters)) scope.listen(byId(`people-filter-${key}`), key === "query" ? "input" : "change", event => { filters[key] = event.target.value; if (person) renderWorks(); });
    if (person) renderProfile(); else if (listing) renderDirectory(); else void browse();
  }
  function unmount() { scope?.dispose(); request?.dispose(); version++; }
  return { mount, unmount, open };
}
