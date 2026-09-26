# Frontend-Bestandsaufnahme vor der Migration

Vollinventar einschließlich DOM-IDs, API-Aufrufen, globalen Symbolen, Storage-Zugriffen, jedem Timer und Router-Verträgen: `frontend-audit.json`. Alle Textdateien unter `web/` und alle `api/api_*_router.py` wurden vollständig eingelesen und strukturell analysiert; PNG ist ein unverändertes Branding-Asset.

## Verhaltensprüfung je Migrationsschritt

| Bereich | JS / DOM | Serverzustand / API | Temporärer Zustand | Live / Timer | Prüfung vor und nach Migration |
|---|---|---|---|---|---|
| Anmeldung | screens/login.js, user-profile.js; login-screen, profile-* | auth/status, auth/login, auth/logout, me/profile-summary | Passwortfelder, Dialog, Fokus | Session-Cookie; 401; verzögerter Fokus | Session-Restore, falsches Passwort, Erstlogin, Logout, Sessionablauf; keine Requests vor Login |
| Startseite | screens/home.js, home_experience_v2.js, daily_top_v2.js, taste_v2.js, home_layout_editor.js, home_rail_runtime.js, home_card_dock.js; tab-home | movies, series, anime, taste, home-layout, Jellyfin | Heroindex, Layoutentwurf, Suche, Hover, Scrollposition | Tageswechsel, Rotation, Hover; Jellyfin-Ereignisse | Identische Rows/Datenquellen, Layout speichern, Empfehlungen, Carousel/Fokus, Lazy-Bilder |
| Discovery / Details | screens/movies.js, series.js, anime.js, aniworld.js, *detail-discovery.js, catalog-runtime.js, trailer-runtime.js | Discovery-Router, TMDB, Jellyfin, queue/add | Filter, Seite, Detailauswahl, Trailer | Metadaten-Nachladen, Trailerverzögerung; Queue/Jellyfin-Events | Film/Serie/Anime suchen, paginieren, öffnen, schließen, Download starten |
| Suche | global-search-runtime.js, screens/home.js; global-search-page | movies, series, anime, movie-collections | Query, Scope, Requestsequenz, Jellyfinfilter | kein eigenes Socket | Späte Antworten überschreiben neuere Suche nicht; Escape/Fokus |
| Queue | core.js, app.js, movie_download_feedback.js; queue-* | queue, queue/history, queue/jobs/*; Server bleibt maßgeblich | Darstellungsfortschritt, Dock offen | progress, job_done, queue_started/update/done; Reconnect | Snapshot plus Livefortschritt, Abbruch, Retry, Abschluss, parallele Jobs, Reconnect ohne Doppelverbindung |
| Abos / Notifications | screens/library.js, notifications.js; tab-bibliothek | watchlist, movie-subscriptions; Library-Router | Filter, Auswahl, Sortierung, gelesene Darstellung | watchlist_update, movie_subscriptions_update | Abo anlegen/löschen, Check, Inbox, Lesestatus |
| Kalender | screens/series-calendar.js; tab-kalender | series-calendar | Woche, Filter, Auswahl | Request-Watchdog und Sicherheitsintervall | Laden/leer/Fehler, Fokus, Timeout, schneller Tabwechsel |
| Releases (Pilot) | screens/movie-releases.js; tab-releases, release-settings | releases, releases/check, releases/config, releases/test | Plattform, Zeitraum, Medientyp, Query | 3s Polling nur solange Backend loading/checking; kein passendes WS-Ereignis | Laden/leer/Fehler, Filter/Fokus, Royal-Treffer öffnen, Prüfung, Region/Key speichern/löschen; Wegnavigation stoppt Requests und Polling |
| Einstellungen / Integrationen | screens/settings.js, account.js, setup.js, module-manager.js, automation-policy.js | Administration-, Setup-, Modul-, Automation-Router | Formularentwurf, Sektion, Status | Updater-Polling, Modulstatus, Policy-Intervall | Speichern/Testen, Module, Setup, Update/Serverrestart |
| Storage / Archive | storage-manager.js, storage-move-jobs.js | Storage-Router; backendpersistente Dateien/Jobs | Pfad, Auswahl, Fortschrittsanzeige | Storage-Polling, Move-Polling | Verzeichnisse, Move-Status, Fehler, Tabwechsel |
| Gemeinsame Laufzeit | api.js, store.js, i18n.js, jellyfin-resume.js, loading.js | Konfiguration, Sprache, Buildversion | Legacy state mischt Serverkopien und UI; wird schrittweise zerlegt | Build-Heartbeat; Resume-Puls; Übersetzungsdebounce | Reload, Serverrestart, Sprache, Offline/Online, mobile Darstellung |

## Gemeinsame Komponenten und Storage

Media Cards/Artwork/Badges werden von Home, Suche, Discovery und Details benutzt; bestehende Dekoratoren überschreiben globale Funktionen. Carousel, Modal, Queue-Item und Statusdarstellung sind deshalb explizite Extraktionsgrenzen. Stylesheet-Reihenfolge ist Teil des visuellen Vertrags. `style-tokens.css` enthält bereits die Royal-Farbpalette.

Cookies authentifizieren HTTP und `/ws`; keine neuen Tokens im Browser speichern. localStorage/sessionStorage-Zugriffe sind im Vollinventar pro Datei aufgeführt. Persistente Konfiguration, Profile, Abos, Requests, Jobs und Bibliothek bleiben ausschließlich backendgeführt. Filter, Entwürfe und Scrollzustände gehören dem Feature. Sprache, Benutzer und Verbindungsstatus gehören in den Shared Store.

## Timerentscheidung

Jeder bestehende Timer steht mit Zeilennummer im Vollinventar. Kategorien: (1) Netzwerkdeadline: zentraler HTTP-Abbruch; (2) Reconnect: einziger Socket-Manager; (3) Release/Storage/Updater-Polling: nur bei fehlendem WS-Vertrag und begrenzt auf aktiven Besitzer; (4) Hero/Trailer/Hover/Fokus: View-Lifecycle; (5) Tageswechsel/Standby/Build: Anwendungslifecycle; (6) verzögerte Scriptinstallation: Übergangskompatibilität, bei Modulmigration entfernen. Aktive Migrationen müssen konkrete Tests für den betreffenden Timer ergänzen; das Inventar alleine bestätigt keine Bereinigung.

## Bekannte Verträge

`/ws` liefert die vorhandenen Nachrichtentypen; der Server antwortet nicht auf App-Ping mit Pong. Deshalb keinen erfundenen Heartbeat/Pong-Timeout einführen. Browser/Server-Protokollping und Reconnect-Snapshots bleiben maßgeblich.

`core/personal_requests.py` persistiert User Requests bereits unabhängig von Queue und Retry. `GET /api/me/profile-summary` liefert `recent_downloads` aus diesem Store; keine neue Queue-basierte Historie und kein zweiter Store. Bestehende Tests: `test_personal_requests.py`, `test_profile_hub_presentation.py`.
