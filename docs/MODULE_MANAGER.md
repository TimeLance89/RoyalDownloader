# Module Manager

RoyalDownloader bleibt mit allen optionalen Modulen ausgeschaltet ein voll nutzbarer Downloader. Authentifizierung, Persistenz, Queue, Downloads, Katalog, Provider-Auflösung und Sicherheitsgrenzen sind deshalb Core und nie Modulschalter.

## Architektur

`core/module_manager.py` enthält den generischen Graphen, den persistierten Aktivierungswunsch und den beobachtbaren Runtime-Zustand. `modules/registry.py` enthält die Built-in-Manifeste. Konkrete Worker liegen in `modules/builtin_workers.py`; dort werden sie über `WorkerModuleController` registriert. Der FastAPI-Server registriert lediglich alle Built-ins und besitzt weder Modul-`if`- noch Modul-`elif`-Lifecycle-Zweige.

Ein Controller stellt `start()`, `stop()`, `health()` und `configuration_state()` bereit. `stop()` ist nur erfolgreich, wenn der zugehörige Thread tatsächlich beendet ist. Der Manager protokolliert Start, Ende und Fehler, isoliert Fehler eines optionalen Moduls und startet den Core trotzdem weiter.

## Vier getrennte Zustände

| Feld | Bedeutung |
|---|---|
| `enabled` | Persistierter Nutzerwunsch für das Modul. |
| `configured` | Zugangsdaten bzw. notwendige Modulkonfiguration sind vorhanden. |
| `runtime_status` | `disabled`, `starting`, `running`, `stopping`, `needs_configuration` oder `error`. |
| `health` | Reale Workerprüfung, nicht nur ein gesetztes Event. |

Ein aktiviertes Telegram-Modul ohne Token ist damit `needs_configuration`, nicht `running`. Ein Thread, dessen Stop-Timeout abläuft, bleibt `stopping`; er wird nicht als beendet dargestellt.

## Persistenz, Start und Stop

Der Zustand liegt rückwärtskompatibel als `module.<id> = true|false` in `settings.ini`. Fehlende Schlüssel bedeuten für bestehende Installationen weiterhin **aktiv**. Das verhindert eine überraschende Deaktivierung von bereits genutztem Seerr, Telegram, Jellyfin-Recommender oder automatischen Updates.

Bei einer Änderung wird zuerst der Lifecycle ausgeführt und danach der neue Zustand gespeichert. Ein nicht beendeter Worker wird nicht persistiert deaktiviert. Schlägt das Schreiben fehl, wird der vorherige Workerzustand wiederhergestellt und der RAM-Zustand bleibt unverändert. Ein fehlgeschlagener Start wird dagegen als sichtbarer Runtime-Fehler bei gespeichertem Aktivierungswunsch geführt; er blockiert weder Core noch andere Module und kann nach Konfigurationskorrektur oder Neustart erneut starten.

Beim Start werden nur persistiert aktivierte Module in Dependency-Reihenfolge gestartet. Beim Shutdown werden sie in umgekehrter Reihenfolge gestoppt, ohne den persistierten Wunsch zu verändern. Dadurch startet ein deaktiviertes Modul nach Neustart nicht, ein aktiviertes genau einmal.

## Dependencies

- `requires` wird transitiv aktiviert; ein Einschalten von C aktiviert bei C → B → A auch B und A.
- Das Ausschalten einer benötigten Dependency wird mit HTTP 409 abgelehnt. `cascade=true` beendet alle transitiven Dependents zuerst.
- `optional_requires` blockiert nie den Start. Fehlende optionale Module erscheinen als reduzierte Capability im API-Payload und UI.
- `conflicts` werden in beide Richtungen vor dem Start abgewiesen.
- Unbekannte IDs, doppelte IDs und Required-Dependency-Zyklen werden beim Manager-Aufbau abgewiesen.

## Eingebaute Module

| Modul | Tatsächliche Wirkung beim Deaktivieren | Konfiguration innerhalb des Moduls |
|---|---|---|
| `jellyfin-recommendations` | Stoppt ausschließlich den periodischen Jellyfin-Recommender. Bestehende Bibliothek, Downloads und gespeicherte Taste-Daten bleiben Core. | Jellyfin-URL und API-Key. |
| `seerr-sync` | Stoppt die Seerr-Request-Bridge; der manuelle Seerr-Abgleich liefert einen definierten `409 module_unavailable`. Gespeicherte Request-Historie bleibt lesbar. | Adresse, API-Key, Pollintervall und Sync-Verhalten. |
| `telegram-control` | Stoppt den Telegram-Long-Polling-Worker. | Token, Chat-ID und die Telegram-Integrationseinstellung. |
| `automatic-updates` | Stoppt nur die Background-Prüfer. Manuelle Versionsprüfung, Installation und Rollback bleiben Core. | Update-Modus/Intervall; die yt-dlp-Runtime-Prüfung bleibt zusätzlich opt-in. |

Die Integrationsschalter in den jeweiligen Einstellungsformularen beschreiben Zugangsdaten oder das Verhalten *innerhalb* eines vorhandenen Moduls. Der Modulschalter steuert ausschließlich die Lebensdauer seiner Background-Worker. So bleibt manuelle Wartung auch bei ausgeschalteten automatischen Updates verfügbar.

## API und UI

`GET /api/modules` und `GET /api/v1/modules` sind die autoritative Modulquelle für das Frontend. Jeder Eintrag enthält Manifest, `enabled`, Konfiguration, Runtime, Health, Fehler, Dienste und Dependency-Informationen. `PUT /api/modules/{id}` speichert sofort; der Modulbereich stoppt `input`- und `change`-Events deshalb vor dem globalen Settings-Dirty-State.

Feature-Routen dürfen deaktivierte Module nicht stillschweigend benutzen. Der manuelle Seerr-Abgleich prüft über den Manager und liefert bei deaktiviertem, nicht konfiguriertem oder nicht laufendem Modul `409` mit `code: module_unavailable`. Konfigurations- und Read-only-Endpunkte bleiben erreichbar, damit das Modul wieder eingerichtet werden kann.

## Feature-Inventar

| Bereich | Klasse | Hintergrundarbeit / Abhängigkeiten | Auswirkung beim Deaktivieren / Empfehlung |
|---|---|---|---|
| Auth, Autorisierung, Security-Middleware, Setup | Core | Session- und Sicherheitsgrenzen | Nie optionalisieren. |
| Konfiguration, Migration, Persistenz, Medienpfade | Core | Dateisystem- und Recovery-Jobs | Nie optionalisieren. |
| Downloads, Queue, Staging, Provider-Auflösung | Core | Queue-Worker, Probe- und Retrylogik | Grundfunktion des Downloaders. |
| Suche, Katalog, Filme, Serien, Collections, Metadaten | Core | Caches und Metadatenabrufe | Grundfunktion; Provider und Sprache sind Konfiguration. |
| Watchlist, Abos, automatische Episoden-/Filmprüfungen | Core | Scheduler und Queue-Übergaben | Fachlicher Downloader-Kern, nicht separat schaltbar. |
| Jellyfin Live/Ownership, Bibliotheksabgleich | Core-Integration | Live-Probes und Cache | Schützt vor doppelten Downloads; Zugangsdaten sind Konfiguration. |
| Jellyfin-Empfehlungen | Modul | Periodischer Recommender | Siehe `jellyfin-recommendations`. |
| Seerr | Modul | Polling-Bridge, Moonfin-Abgleich | Siehe `seerr-sync`. |
| Telegram | Modul | Long Polling | Siehe `telegram-control`. |
| Update-Engine, Versionsinfo, Installation, Rollback | Core | Explizit vom Nutzer ausgelöst | Muss bei deaktiviertem Auto-Update nutzbar bleiben. |
| Automatische Update-/yt-dlp-Prüfung | Modul + Capability | Zwei Background-Worker, yt-dlp opt-in | Siehe `automatic-updates`. |
| Storage Manager und Move-Jobs | Core-Wartung | Bewusste, vom Nutzer gestartete Jobs | Keine dauerhafte optionale Fähigkeit. |
| Serienkalender, Movie Releases, Daily Top | Core-Discovery | Caches/periodische Aktualisierung | Teil der Standardoberfläche; später nur nach klarer Entkopplung Kandidat. |
| Taste Profile und Recommendations-Daten | Core-Discovery | Lokale Datenpflege | Keine eigenständige externe Workergrenze. |
| Home-Layout, Trailer, UI-Übersetzung | Core-UI / Konfiguration | Keine unabhängige Dienstgrenze | Nicht modulieren. |
| Automation, Smart Automation, Benachrichtigungen | Core-Workflow | Queue-nahe Regeln | Erst nach separatem Worker und API-Grenze Kandidat. |
| Anime/AniWorld und weitere Provider | Provider-Konfiguration | Provideradapter | Keine Module: sie sind austauschbare Quellen innerhalb der Suche. |
| KI-Discovery, JEV, Decision Engine | Nicht implementiert | — | Ausdrücklich nicht Bestandteil dieser Architektur. |

## Neues Built-in hinzufügen

1. Ein eindeutiges `ModuleManifest` in `modules/registry.py` anlegen und nur seriöse Ressourcen-/Serviceangaben eintragen.
2. Einen Controller im Modulbereich implementieren. Start, Stop und Health müssen reale Workerzustände prüfen; Stop muss nach Timeout `False` liefern.
3. Den Controller in `modules/builtin_workers.py` oder dem eigenen Modul registrieren. `server.py` wird nicht mit einem neuen Spezialfall ergänzt.
4. Erforderliche, optionale und konfliktäre Dependencies im Manifest modellieren.
5. Feature-APIs über `ModuleManager.availability()` schützen, UI über `/api/modules` steuern und Konfigurationsseiten weiter erreichbar halten.
6. Persistenz-, Graph-, Start/Stop-, Parallel- und API-Tests ergänzen.

## Grenzen

Dies ist bewusst kein Third-Party-Plugin-System: keine ZIP-Installation, kein Marketplace und kein Remote-Code. Built-ins laufen im selben Prozess und dürfen keine Authentifizierung, Validierung oder Persistenzgrenzen umgehen.
