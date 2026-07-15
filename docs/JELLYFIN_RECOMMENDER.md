# Jellyfin-Empfehlungen

[← Projektübersicht](../README.md) · [Docker-/NAS-Anleitung](DOCKER.md)

Der bestehende `seriendownloader`-Server erstellt die globale Collection
„Für dich empfohlen“. Der erste Lauf startet direkt mit dem Server, weitere
Läufe folgen täglich. Nach geänderten Jellyfin-Einstellungen wird sofort neu
gerechnet.

## Start

Jellyfin-URL, API-Schlüssel und Benutzer in der Weboberfläche speichern. Im
Container liegen sie persistent unter
`/app/data/FilmeDownloader/settings.ini` (Host-Mount:
`./data/FilmeDownloader/settings.ini`). Danach den normalen Server starten:

```bash
docker compose up -d --build
docker compose logs -f seriendownloader
```

Ein alter separater `jellyfin-recommender`-Container muss gestoppt werden, damit
nicht zwei Prozesse dieselbe Collection aktualisieren.

## Optionale Umgebungsvariablen

| Variable | Default | Bedeutung |
|---|---:|---|
| `COLLECTION_NAME` | `Für dich empfohlen` | Exakter Collection-Name |
| `TOP_N` | `20` | Maximale Anzahl Empfehlungen |
| `RECENCY_HALF_LIFE_DAYS` | `180` | Aktualitätsgewichtung; `0` deaktiviert sie |
| `RECOMMENDER_INTERVAL_SECONDS` | `86400` | Abstand zwischen Läufen, mindestens 60 Sekunden |
| `REQUEST_TIMEOUT_SECONDS` | `120` | Jellyfin-Lese-Timeout |
| `PAGE_SIZE` | `100` | Seitengröße der schweren Metadatenabfrage; maximal 100 |

Die Collection-ID bleibt bei Aktualisierungen stabil. Bei fehlenden Daten,
fehlendem Profil oder doppelten gleichnamigen Collections wird die bestehende
Collection nicht destruktiv verändert. Fehlgeschlagene Läufe werden nach
15 Minuten erneut versucht. Fehlt der Collection ein Primärbild, wird einmalig
das Poster der bestbewerteten Empfehlung übernommen. Ein vorhandenes oder
manuell gesetztes Collection-Cover bleibt unverändert.
