# Filmwelten & Studios (RoyalDownloader)

Die Filmregie unter **Filme → Filmwelten & Studios** nutzt eine gemeinsame,
kuratiert gepflegte Quelle: `integrations/movie_world_catalog.json`.

## Kategorien

- `discover`: unabhängige TMDB-/discover/movie-Kataloge auf Grundlage stabiler
  Produktionsfirma-IDs. Disney Classics schränkt das Ergebnis zusätzlich über
  Animation/den Ausschluss von Pixar ein.
- `collections`: offizielle TMDB-Filmkollektionen. Die Definition enthält
  stabile IDs (wenn bekannt) oder deren englische, geprüfte Kollektionsnamen.
  Die Suche akzeptiert ausschließlich exakt übereinstimmende Namen (mit oder
  ohne „The“ und „Collection“), nicht beliebige ähnliche Stichworttreffer.
- Mehrere Kollektionen können einer Filmwelt zugeordnet sein (z. B. Mittelerde).
  Doppelte TMDB-Film-IDs werden zusammengeführt.

## Schnittstellen

- `GET /api/movie-worlds/catalog` (und `/api/v1/movie-worlds/catalog`):
  Liefert ausschließlich Labels, IDs und Gruppen. Dieser Endpunkt funktioniert
  auch ohne TMDB-API-Schlüssel.
- `GET /api/movies?mode=world&world=...&page=...&language=...`:
  Liefert TMDB-Metadaten, serverseitige Filter und Paginierung. Bei Filmreihen
  ergänzt er `collections: [{collection_id, title}]` für die vorhandene
  Vervollständigen-Funktion.
- Die Anbieter- und Jellyfin-Prüfungen erfolgen erst beim Öffnen eines Films
  oder über den bestehenden Sammlungsdialog; TMDB allein ist kein Nachweis
  für eine tatsächliche Download- oder Tonspurverfügbarkeit.

## UI und Wartung

`web/js/features/discovery/movie-world-explorer.js` bietet Live-Suche,
Themenfilter, Tastaturbedienung und mobile Filmwelt-Karten. Das vorhandene
`#movie-filter-world`-Dropdown bleibt zur Abwärtskompatibilität und bei einem
Ausfall des Katalog-Endpunkts erhalten.

Neue Studio-/Filmreihen-Einträge werden in der JSON-Datei gepflegt und sind
anschließend automatisch auf Backend und Frontend verfügbar. Für unbekannte
Reihen ohne offizielle TMDB-Kollektion bitte keine beliebigen Film-Suchtreffer
als feste Reihen ausgeben: stattdessen verifizierte TMDB-Metadaten oder
künftig eine separate, explizit kuratierte Liste verwenden.

## Regressionstests

- `tests/test_movie_worlds.py`: Filter, Cache, korrekte TMDB-Zuordnung,
  Kombinations-Welten, Serverkatalog und leere/unbekannte Kollektionen.
- `tests/frontend/movie-worlds-browser.cjs`: Suche, Sprache,
  Filter, Karten-Auswahl, Nachladen und Vervollständigen-Aktion.
- `tests/movie_catalog_refresh.test.mjs`: bestehende DOM-Mocks und
  Lebenszyklus des Filmbrowsers.
