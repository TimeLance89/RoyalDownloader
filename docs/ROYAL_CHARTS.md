# Royal Charts Engine 3.0

## Ranking

Jeder Titel braucht einen Eintrag in einer aktiven Quelle, nutzbares Artwork und ein positives Popularitätssignal. Der Tagesscore besteht zu 90 % aus Popularität und zu 10 % aus Qualität. Der Rangwert ist `100 / (1 + 0,12 × (Rang − 1))`. Er misst die Position innerhalb einer Liste, unabhängig von absoluten Abrufzahlen.

- Die Engine verwendet das stärkste gewichtete Popularitätssignal. Gemessene Aufruf- und Trending-Ränge zählen voll. Der TMDB-Popularitätskatalog von Huhu zählt mit Faktor 0,80. Top- und Highlight-Rubriken ohne belegte Aufrufsortierung zählen mit Faktor 0,55.
- Huhu und TMDB-Trending bilden eine gemeinsame Signalgruppe. Listen mit mindestens drei identischen, gleich angeordneten Titel-Jahr-Paaren über die gesamte beobachtete Seite werden zusammengefasst. Weitere Provider erhöhen den Score durch einen stärkeren Messwert. Die Anzahl der Quellen beeinflusst die Konfidenz und vergibt keine Punkte.
- Der Qualitätsscore nutzt TMDB-Bewertung und logarithmisch gewichtete Stimmen. Fehlen diese Daten, kann der stärkste beobachtete Bewertungsrang mit Faktor 0,55 einspringen. FilmFrei24 sortiert nach TMDB-Bewertung und Stimmen und wird dabei nur einmal berücksichtigt. Neuheiten und sonstige Katalogpositionen dienen zur Kandidatensuche.
- Identitäten trennen Filme und Serien. Explizite TMDB-IDs haben Vorrang. Exakte normalisierte Titel und Erscheinungsjahre können dieselbe Produktion verbinden. Lokalisierte und Originaltitel werden für den Abgleich verwendet. Jahrlose Einträge bleiben quellspezifisch, bis eine eindeutige TMDB-Suche oder ein bestätigter Quellbezug vorliegt. Mehrdeutige Treffer bleiben getrennt. Identitäten brechen Score-Gleichstände deterministisch.
- In den ersten zehn gemischten Plätzen kann die Auswahl sieben Plätze der dominanten Medienart vorsehen, wenn drei Titel der anderen Art mindestens 18 Punkte und 34 % des Spitzenscores erreichen. Der Rest folgt dem Score.

### Audit der lokalen Adapter

| Provider | Filme | Serien | Lokaler Beleg |
| --- | --- | --- | --- |
| MegaKino | `views_rank` | `recent_uploads` | Filmabfrage mit `views`, Serien mit `updates` |
| SerienStream | — | `views_rank` | Rubrik „Meistgesehen gerade“ |
| SFlix | `trending_rank` | `unknown` | Nur die Filmrubrik `#trending-movies` zählt. Serien kommen aus dem Katalog. |
| KinoKing | `editorial_top` | `unknown` | `top10-movies` und `current-series` |
| Filmpalast | `editorial_top` | `recent_uploads` | `/movies/top` mit unbekannter Sortiergrundlage und zuletzt aktualisierte Serien |
| Ridomovies | `editorial_top` | `recent_uploads` | Film-Highlights und `/api/tv/latest` |
| Huhu | `popularity_rank` | `popularity_rank` | `tmdb.movie` und `tmdb.series`, jeweils `sort=popularity` |
| Filmo | `rating_rank` | — | `rating_desc` |
| FilmFrei24 | `rating_rank` | — | TMDB-Bewertung, Stimmen, Upload-Datum als letzter Sortierschlüssel |
| XCine | `rating_rank` | `recent_uploads` | Filme nach `rating`, Serien nach `latest` |
| KinoGer | `recent_uploads` | `unknown` | Chronologische Film-Hauptliste, Serienkategorie |
| Kinox | `recent_uploads` | — | RSS-Neuheiten |
| Einschalten | `recent_uploads` | — | Als Neuheiten dokumentierter Filmkatalog |
| Moflix | `unknown` | `unknown` | Filme teilen dieselbe Liste für Top und Neu, Serien aus `/series` |
| FlixiTV, Movie2k, HDFilme Family | `unknown` | `unknown` | Katalogseiten ohne belegte Popularitätssortierung |
| KellerKino | `unknown` | — | Filmarchiv |
| VidSrc, VidRift, VixSrc, VidRock, VidLink, MovieBox | `unknown` | `unknown` | Detail-/Embed-Quellen ohne eigene Chart-Liste im verwendeten Katalogpfad |
| AniWorld, MKissa | — | — | Separater Anime-Katalog |
| TMDB | `trending_rank` | `trending_rank` | `/trending/movie/day` und `/trending/tv/day` |

## Erfassung und Verlauf

`royal_charts.sqlite3` entsteht automatisch neben `settings.ini`. In Docker ist das normalerweise `/app/data/FilmeDownloader/royal_charts.sqlite3` im vorhandenen `./data`-Mount. Die neue Datenbank ist unabhängig von den bestehenden Einstellungen und Downloads. Die Erfassung beginnt mit dem ersten verfügbaren Tagesstand.

Der Tag beginnt um **00:00 UTC**. Der Runtime-Wartungszyklus stößt die Berechnung auf konfigurierten Installationen an. Ein Chart-Abruf kann sie vorziehen. Ein Hintergrundworker und eine transaktionale SQLite-Reservierung teilen die Arbeit zwischen parallelen Anfragen und verhindern doppelte Schreibvorgänge. Ein publizierter Stand ist bis zum Tageswechsel stabil. Leere Versuche können nach 15 Minuten wiederholt werden.

Der Schlüssel enthält die wirksamen Provider und deren Reihenfolge, Inhaltssprachen und die TMDB-Konfiguration. Die lokale Anwendung konfiguriert diese Quellen serverweit. Haushaltsprofile mit demselben Quellensatz teilen die allgemeine Rangliste. „Nicht für mich“ beeinflusst die Anzeige pro Profil.

Die Datenbank hält 90 Kalendertage mit bis zu 30 Titeln pro Tag und Konfiguration. Enthalten sind Zeitstempel, Algorithmusversion, Identität, Position, Score-Komponenten, Providerbelege und Konfidenz. Ein begrenzter Erstfundindex für aktive Konfigurationen erkennt auch ältere Wiedereinstiege über identische Medien-IDs. Die Säuberung erfolgt bei der täglichen Erfassung. Alter Verlauf fehlt bei längerer Inaktivität oder neuer Konfiguration. Bestplatzierung und Chart-Tage beziehen sich auf die gespeicherten 90 Tage.

- Positionsbewegungen benötigen den unmittelbaren Vortag mit vergleichbarer Quellenabdeckung. `NEW` markiert den ersten erfassten Auftritt nach einem vergleichbaren Tagesstand. `RE` benötigt einen nachgewiesenen früheren Auftritt und einen fehlenden Platz am Vortag.
- Die rollierenden 7- und 30-Tage-Wertungen brauchen mindestens zwei erfasste Tage. Der Tagesbeitrag besteht zu 60 % aus Platzierung und zu 40 % aus Popularität. Neuere Tage erhalten das Gewicht `1 / (1 + Alter_in_Tagen / 7)`. Die Summe wird durch die Gewichte aller erfassten Tage geteilt, sodass wiederholte Auftritte zählen.
- Durchstarter brauchen einen mittleren Zuwachs von mindestens fünf Punkten zwischen den echten Rangwerten gemeinsamer Quellen am Vortag und am aktuellen Tag. Die Rubrik ist auf Titel beschränkt, die an beiden Tagen in den Top 30 standen. Ein neu hinzugekommener Provider liefert für sich keinen Zuwachs.
- Verlaufspunkte unterscheiden einen fehlenden Tagesstand von einem erfassten Tag ohne Chart-Platz. Mehrdeutige Identitäten, Quellenwechsel und fehlende Messungen können Bewegungsangaben unterdrücken. Die Konfidenz bewertet beobachtbare Signalgruppen, deren tatsächliche Unabhängigkeit bei unbekannten Upstreams offenbleibt.

## API und Oberfläche

| Pfad | Verhalten |
| --- | --- |
| `GET /api/daily-top` und `GET /api/v1/daily-top` | Kompatible Tagesroute mit `version: 2`, optionalem `period`, bisherigen Kandidaten- und Navigationsfeldern. Die Score-Komponenten heißen jetzt `popularity` und `quality`. |
| `GET /api/v3/royal-charts` | `mode=today\|week\|month\|breakouts\|new`, `kind=mixed\|movie\|series`, optional `genre` und `period=YYYY-MM-DD`. Liefert API- und Algorithmusversion, gemessene Quellen, Tages- und Modusposition, Historie und den Grund einer leeren Liste. Historische Abrufe lesen gespeicherte Stände. |

Die Home-Reihe ergänzt drei Schaltflächen am bestehenden Karussell. „Alle Charts entdecken“ öffnet eine eigene Ansicht im Dialog mit fünf Wertungen und Medien-/Genre-Filtern innerhalb der Top 30. Das Info-Symbol zeigt die Score-Grundlage und den 7-/30-Tage-Verlauf per Klick, Tastatur und Touch. Die Poster verwenden die bestehenden Medienkarten samt Goldrängen, Jellyfin-Status und Detailnavigation.

Provider-Health, Cooldowns und die vorhandenen Katalogpools begrenzen die Abfragen. Die Erfassung liest je Provider höchstens eine Seite und wertet maximal 30 Einträge aus. TMDB nutzt bis zu zwei Trendseiten und bis zu 16 Titelabgleiche je Medienart. Bereits publizierte Stände und explizite Abrufe vergangener Tage kommen aus SQLite. Genre-Filter sind auf Titel mit erfassten Genres beschränkt. Die Oberfläche hält Modi im Speicher, solange Home geöffnet ist, und plant eine Aktualisierung am UTC-Tageswechsel.

## Prüfung

Die Browserprüfung läuft lokal mit Playwright und simulierten API-Antworten. Sie prüft Moduswechsel, Lade- und Fehlerzustand, Rangnummern, Chart-Details, Film-/Seriennavigation, Jellyfin-Anzeige, Feedback und Touch. Die Screenshots verwenden Testposter. Provider-Verfügbarkeit und Darstellung auf der produktiven NAS-Installation sind außerhalb dieses Testlaufs.

Lokal bestanden 209 ausgewählte Python-Tests für Charts, Home, Discovery, Provider und NAS-Laufzeit sowie alle 248 Tests in `tests/frontend/*.test.*`. `royal-charts-browser.cjs` lief bei 1440 und 390 Pixel Breite. `browser-smoke.cjs`, `mobile-browser.cjs`, Ruff mit den Prüfregeln des Projekts und `git diff --check` waren ebenfalls erfolgreich.

## Dateien

- Backend und Provider · `application_services/daily_top.py`, `application_services/chart_history.py`, `application_services/movie_catalog.py`, `application_services/series_catalog.py`, `application_services/series_catalog_cache.py`, `application_services/runtime_maintenance.py`, `providers/sflix.py`, `providers/ridomovies.py`.
- Frontend · `web/index.html`, `web/style.css`, `web/styles/daily-top.css`, `web/js/composition/home.js`, `web/js/features/home/daily-top.js`, `web/js/features/home/actions.js`, `web/js/features/home/lanes.js`, `web/js/features/home/presenter.js`, `web/js/features/home/rail-renderer.js`, `web/js/features/home/rows.js`.
- Tests · `tests/test_daily_top_v2.py`, `tests/test_daily_top_frontend_v2.py`, `tests/test_nas_runtime_stability.py`, `tests/frontend/core.test.mjs`, `tests/frontend/royal-charts-browser.cjs`.
- Dokumentation · `docs/ROYAL_CHARTS.md`.
- Lokale Screenshots · `artifacts/royal-charts-v3/desktop.png`, `artifacts/royal-charts-v3/mobile.png`, `artifacts/royal-charts-v3/charts-desktop.png`, `artifacts/royal-charts-v3/charts-mobile.png`.
