# Frontend-Härtung: technische Bestandsaufnahme

Ausgangsstand: `16e7b58b`, vor Änderungen an der Laufzeit.

## Importgraph und Registry

154 Module unter `web/js/`. Vollständiger Importgraph sowie alle Registry-Zugriffe
mit Dateiname, Zeile, Schlüssel und Schreibmarkierung stehen in
[frontend-hardening-audit.json](frontend-hardening-audit.json).

Eine zyklische Gruppe mit sieben Modulen:

```text
shell/presentation.js
shell/actions/settings.js
shell/actions/home.js
shell/actions/series.js
shell/actions/anime.js
shell/actions/movies.js
shell/actions/aniworld.js
```

514 direkte Registry-Zugriffe, 98 registrierte Eigenschaften/Schreibstellen.
`composition.js` erzeugt Dienste; Shell-Dateien lesen sie und vermitteln
fachliche Operationen. Dadurch sind Aufbau und Aufrufe indirekt gekoppelt.

| Datei | direkte Registry-Zugriffe |
| --- | ---: |
| `web/js/composition.js` | 186 |
| `web/js/shell/actions/anime.js` | 12 |
| `web/js/shell/actions/aniworld.js` | 13 |
| `web/js/shell/actions/home.js` | 93 |
| `web/js/shell/actions/library.js` | 21 |
| `web/js/shell/actions/movie-collections.js` | 2 |
| `web/js/shell/actions/movies.js` | 86 |
| `web/js/shell/actions/movie_download_feedback.js` | 5 |
| `web/js/shell/actions/series.js` | 54 |
| `web/js/shell/actions/settings.js` | 5 |
| `web/js/shell/actions/user-profile.js` | 9 |
| `web/js/shell/presentation.js` | 28 |

## Verantwortung der bisherigen Komposition

- Boot: Übersetzung, Startvorhang, Versionsmonitor, Anmeldung, Setup.
- Shell: Navigation, Modals, Queue-Dock, übergreifende Aktionen.
- Discovery: Film-/Serienzustand, Kataloge, Details, Anime/AniWorld, Filmreihen.
- Home: Cache, Katalog, Hero, Reihen, Empfehlungen, Ranking, Layout, Suche.
- Downloads: Queue, Synchronisierung und Live-Ereignisse.
- Profil: Benutzer, Haushalt, Geschmack und Onboarding.
- Abos: Datenmodelle, Regeln, Bibliothek, Kurzansicht und Benachrichtigungen.
- Integrationen/Einstellungen: Provider, Jellyfin, externe Dienste, Speicher,
  Automation, Konto und Updater.
- Start der Feature-Lifecycles und zahlreiche Cross-Domain-Callbacks.

## Zielmodule und Reihenfolge

A. Dieses Audit unverändert als Vorher-Befund sichern.
B. `composition/` in Core/Shell, Discovery, Home, Downloads, Profil, Abos,
   Integrationen und Einstellungen aufteilen. Bestehende Erzeugungsreihenfolge
   zunächst erhalten; anschließend Unit- und Browserprüfung.
C. Einen kleinen Bereich (Profil-/Benutzeraktionen) auf Factory und explizite
   Abhängigkeiten umstellen; zugehörige Registry-Zugriffe entfernen.
D. Home, Discovery und Downloads in weiteren geprüften Schritten umstellen.
   Gegenseitige Aktionen werden als benannte Callbacks verbunden, nicht importiert.
E. Fachliche Aktionen unter `features/` verschieben; Shell nur für Shell-UI halten.
F. Lifecycle-Argumente nach Domänen gruppieren. Keine Ersatz-Service-Registry.
G. Importgraph-/Layering-Tests mit Zyklenerkennung und Negativfällen ergänzen.
H. Browser-Smoke, Setup und unveränderten CSS-Baseline-Test als CI-Job ausführen.
I. Aktuelles `main` integrieren, Konflikte einzeln prüfen, komplette Regression
   einschließlich CI/CodeQL ausführen und Dokumentation aktualisieren.

## Branch-Stand

`overnight` ist beim Audit 41 Commits voraus und 7 hinter `main`.
Die tatsächliche Inhaltsdifferenz außerhalb des Refactors betrifft insbesondere
die Provider-Dokumentation; die Historie enthält bereits übernommene Änderungen.
Die Integration erfolgt als normaler Merge mit Inhaltsprüfung, nicht durch
Ersetzen des modularen Frontends durch die alten Main-Dateien.
