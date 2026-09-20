# Module Manager

Der Module Manager verwaltet ausschließlich optionale Built-in-Erweiterungen. Er ist kein Schalter vor beliebigem Code: jedes Modul besitzt ein Manifest, einen persistierten Zustand und einen Lifecycle-Hook. Beim Abschalten werden die zugeordneten Worker beendet.

## Klassifikation

| Bereich | Klasse | Begründung |
|---|---|---|
| Authentifizierung, Sicherheits-Middleware, Konfiguration, Persistenz | Core | Schützt Zugang und Datenintegrität. |
| Queue, Download-Lifecycle, Provider-Auflösung, Medienpfade | Core | Der Downloader muss ohne Erweiterungen zuverlässig arbeiten. |
| Katalogsuche, Serien-/Filmverwaltung, Basis-Metadaten | Core | Grundfunktion der Anwendung. |
| Jellyfin-Empfehlungen | Modul | Eigener periodischer Recommender-Worker; Jellyfin selbst bleibt als optionale Integration konfigurierbar. |
| Seerr-Synchronisierung | Modul | Eigener Polling-Worker und externe API. |
| Telegram-Steuerung | Modul | Eigener Long-Polling-Worker und externe API. |
| Automatische Updates | Modul | Eigene Update- und yt-dlp-Worker; manuelle Update-Funktionen bleiben erhalten. |
| KI-Entdeckung, Release-Kalender, Smart Automation | Kandidaten | Aktuell noch eng mit Discovery bzw. Queue-Lifecycle gekoppelt; erst nach Herauslösen ihrer Worker migrieren. |

## Lifecycle und Persistenz

`core/module_manager.py` enthält Registry, Dependency-Graph, Status und Fehlerisolation. Zustände liegen rückwärtskompatibel in `settings.ini` als `module.<id> = true|false`; fehlende Einträge bedeuten aktiviert. Der Server registriert Lifecycle-Hooks für die Worker. Ein Modulfehler setzt nur seinen Status auf `error` und beendet nicht den Core.

## Ressourcen

Das UI verwendet bewusst Kategorien statt erfundener Messwerte. Die Angaben beschreiben den zusätzlichen regelmäßigen Bedarf; konkrete Auslastung hängt von Konfiguration, Bibliothek und externen Diensten ab.
