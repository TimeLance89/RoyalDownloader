export const creditKey = item => `${item.media_type}:${item.tmdb_id}`;
export const defaultFilters = () => ({ type: "all", role: "acting", query: "", sort: "popular", year: "all", release: "all", library: "all" });
export const departments = { Acting: "Schauspiel", Directing: "Regie", Writing: "Drehbuch", Production: "Produktion", Sound: "Ton & Musik", Camera: "Kamera", Art: "Ausstattung", Editing: "Schnitt", Crew: "Weitere Mitwirkung" };
export function isUpcoming(item, today = new Date().toISOString().slice(0, 10)) {
  return /^\d{4}-\d{2}-\d{2}$/.test(item.release_date || "") && item.release_date > today;
}
function libraryMatches(item, filter, statuses) {
  if (filter === "all") return true;
  const status = statuses.get(creditKey(item));
  if (filter === "unchecked") return !status;
  if (filter === "unavailable") return ["unavailable", "blocked", "ambiguous"].includes(status);
  return status === filter;
}
export function filterCredits(credits, { type = "all", role = "acting", query = "", sort = "popular", year = "all", release = "all", library = "all" } = {}, statuses = new Map(), today) {
  const needle = query.trim().toLocaleLowerCase();
  const rating = item => Number(item.vote_count) >= 10 ? Number(item.rating) || 0 : 0;
  return credits.filter(item => (type === "all" || item.media_type === type)
    && (role === "all" || (item.departments || []).includes(role === "acting" ? "Acting" : role))
    && (year === "all" || String(item.year) === year)
    && (release === "all" || (release === "upcoming" ? isUpcoming(item, today) : Boolean(item.release_date) && !isUpcoming(item, today)))
    && libraryMatches(item, library, statuses)
    && (!needle || [item.title, item.original_title, ...(item.roles || [])].join(" ").toLocaleLowerCase().includes(needle)))
    .sort((a, b) => {
      if (sort === "title") return a.title.localeCompare(b.title);
      if (sort === "rating") return rating(b) - rating(a) || Number(b.vote_count || 0) - Number(a.vote_count || 0);
      if (sort === "newest" || sort === "oldest") {
        if (!a.release_date || !b.release_date) return Number(!a.release_date) - Number(!b.release_date);
        return String(sort === "oldest" ? a.release_date : b.release_date).localeCompare(String(sort === "oldest" ? b.release_date : a.release_date));
      }
      return Number(b.popularity || 0) - Number(a.popularity || 0) || a.title.localeCompare(b.title);
    });
}
export function filmCandidate(item, statuses, queued, today) {
  return item.media_type === "movie" && !isUpcoming(item, today)
    && statuses.get(creditKey(item)) !== "owned" && !queued.has(item.slug);
}
export function highlights(credits, department = "Acting") {
  const eligible = credits.filter(item => !isUpcoming(item) && item.cover_url);
  const primary = eligible.filter(item => (item.departments || []).includes(department));
  let candidates = primary.length ? primary : eligible;
  if (department === "Acting") {
    // A show's popularity describes the whole show, not this person's guest role.
    // Prefer characters over self/archival appearances, retaining self credits
    // when those are the person's actual body of work (e.g. a presenter).
    const acting = candidates.filter(item => {
      const characters = item.characters || item.roles || [];
      return !characters.length || characters.some(role =>
        !/^(?:self|himself|herself|themself|themselves|sich selbst|er selbst|sie selbst)\b|\b(?:archive footage|archival footage|archivmaterial)\b/i.test(role.trim()));
    });
    if (acting.length) candidates = acting;
  }
  const ordered = candidates.slice().sort((a, b) =>
    Number(b.vote_count || 0) - Number(a.vote_count || 0)
    || Number(b.rating || 0) - Number(a.rating || 0)
    || a.title.localeCompare(b.title));
  const unique = new Map();
  for (const item of ordered) if (!unique.has(creditKey(item))) unique.set(creditKey(item), item);
  return [...unique.values()].slice(0, 8);
}
