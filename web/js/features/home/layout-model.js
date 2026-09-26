export const HOME_RAIL_CATALOG = [
  { id: "personal", trackId: "home-movies-track", title: "Für dich ausgewählt", eyebrow: "Persönlich", description: "Aus deinen Klicks, Downloads und Favoriten.", layout: "spotlight" },
  { id: "top", trackId: "home-top-track", title: "Top 10", eyebrow: "Tageschart", description: "Was heute über alle Quellen hinweg gefragt ist.", ranked: true },
  { id: "series", trackId: "home-series-track", title: "Serien, die gerade alle sehen", eyebrow: "Serien", description: "Aktuell beliebte Serien aus deinen Quellen." },
  { id: "genre", trackId: "home-genre-track", title: "Ein Genre für dich", eyebrow: "Geschmack", description: "Eine wechselnde Reihe aus deinen Lieblingsgenres." },
  { id: "explore", trackId: "home-explore-track", title: "Heute mal etwas anderes", eyebrow: "Entdecken", description: "Bewusst außerhalb deiner üblichen Auswahl." },
  { id: "gems", trackId: "home-gems-track", title: "Verborgene Schätze", eyebrow: "Geheimtipps", description: "Gut bewertete Titel abseits der Tagescharts." },
  { id: "fresh", trackId: "home-new-track", title: "Neu hinzugefügt", eyebrow: "Gemischt", description: "Neue Filme und Serien in einer Reihe." },
  { id: "new_movies", trackId: "home-new-movies-track", title: "Neue Filme", eyebrow: "Filme", description: "Die neuesten Filme aus allen aktiven Quellen." },
  { id: "new_series", trackId: "home-new-series-track", title: "Neue Serien", eyebrow: "Serien", description: "Neue und frisch aktualisierte Serien." },
  { id: "high_rated", trackId: "home-high-rated-track", title: "Besonders gut bewertet", eyebrow: "Bewertungen", description: "Filme und Serien mit starken Bewertungen." },
  { id: "movies", trackId: "home-movie-night-track", title: "Filmabend", eyebrow: "Nur Filme", description: "Eine täglich neu gemischte Auswahl nur mit Filmen." },
  { id: "library", trackId: "home-library-track", title: "Schon in deiner Mediathek", eyebrow: "Jellyfin", description: "Direkter Zugriff auf bereits vorhandene Titel." },
];
const HOME_DEFAULT_VISIBLE_RAILS = ["personal", "top", "series", "genre", "explore", "gems", "fresh"];
export function defaultHomeLayout() {
  return {
    version: 1, hero_visible: true,
    rail_order: HOME_RAIL_CATALOG.map((rail) => rail.id),
    hidden_rails: HOME_RAIL_CATALOG.map((rail) => rail.id)
      .filter((railId) => !HOME_DEFAULT_VISIBLE_RAILS.includes(railId)),
  };
}

export function normalizeHomeLayout(value) {
  const source = value && typeof value === "object" ? value : {};
  const allowed = new Set(HOME_RAIL_CATALOG.map((rail) => rail.id));
  const order = [];
  for (const raw of Array.isArray(source.rail_order) ? source.rail_order : []) {
    const railId = String(raw || "");
    if (allowed.has(railId) && !order.includes(railId)) order.push(railId);
  }
  HOME_RAIL_CATALOG.forEach((rail) => { if (!order.includes(rail.id)) order.push(rail.id); });
  const hidden = new Set((Array.isArray(source.hidden_rails) ? source.hidden_rails : [])
    .filter((railId) => allowed.has(railId)));
  if (hidden.size === allowed.size) hidden.delete(order[0]);
  return {
    version: 1, hero_visible: source.hero_visible !== false, rail_order: order,
    hidden_rails: order.filter((railId) => hidden.has(railId)),
  };
}
