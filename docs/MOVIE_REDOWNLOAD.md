# Vorhandenen Film vor dem erneuten Download löschen

## Verhalten

Ein API-Client kann nach ausdrücklicher Löschbestätigung einen vorhandenen Film
vor dem erneuten Download ersetzen lassen. Normale Downloads und deren
Duplikatschutz bleiben bestehen. Das Endpoint erfordert einen angemeldeten
Administrator, da die gemeinsame Jellyfin-Bibliothek betroffen ist.

1. Film und verfügbare Quelle serverseitig auflösen.
2. TMDB-ID mit der bestätigten Client-Auswahl vergleichen; Titel und Jahr müssen
   ebenfalls mit den serverseitig ermittelten Metadaten übereinstimmen.
3. Bereits laufende/eingeplante Downloads desselben Films ausschließen.
4. Alle Jellyfin-Filmeinträge mit genau dieser TMDB-ID frisch ermitteln.
5. Ziel-IDs vor der ersten Löschung dauerhaft speichern.
6. Diese Einträge über Jellyfins bestehende DELETE-Funktion löschen. Keine vom
   Client übergebenen Datei-/Verzeichnispfade verwenden.
7. Löschabschluss speichern und beide Jellyfin-Film-Caches frisch abgleichen.
8. Durch die normale Queue-Aufnahme inklusive lokaler Dateiprüfung und
   persistenter persönlicher Anfrage einplanen. Die Quellauflösung kann später
   weiterhin scheitern; bis zum erfolgreichen Download fehlt dann der Film.

Die Quellenprüfung bestätigt vorhandene Hosterangebote, keine garantierte
Erreichbarkeit oder spätere Downloadqualität. Behält Jellyfin Dateien wegen
fehlender Rechte oder meldet weiterhin eine Version, startet kein Ersatzdownload.
Ein lokaler Restbestand wird durch die normale Queue-Prüfung ebenfalls gesperrt.
Serien/Episoden werden von diesem Endpoint ausdrücklich nicht ersetzt.

## API

`POST /api/queue/redownload` oder `/api/v1/queue/redownload`, normale authentifizierte
Sitzung/Mobile-Bearer und bestehende Same-Origin-Prüfung:

```json
{
  "slug": "anbieter:film",
  "tmdb_id": 123,
  "request_id": "5cbb91ee-ae21-480e-ad65-aa9b604be591",
  "preference": {"provider": "anbieter", "quality": "1080p", "hoster_url": ""}
}
```

Erfolg entspricht der Queue-Antwort, zusätzlich `deleted: true`. Erfolg bedeutet
Einplanung, nicht abgeschlossenen Download. Wiederholungen derselben Anfrage
liefern das gespeicherte Ergebnis, ohne eine neue Version zu löschen. Die ID ist
an Benutzer, Film-ID, Slug und Quellenauswahl gebunden. Clients müssen bei einer
Wiederholung dieselbe ID und Auswahl senden. Offene Anfragen sollten vor dem
Senden dauerhaft gesichert und erst nach bestätigter Einplanung entfernt werden.
Ein Server ohne dieses Endpoint meldet 404/405. Clients dürfen dann nicht auf
einen ungeprüften Lösch- oder Queue-Pfad zurückfallen.

## Dauerhaftigkeit und Störungen

`movie_replacements.sqlite3` liegt im bestehenden persistenten Datenverzeichnis
(`SERIENDL_DATA_DIR`, sonst Projektordner). Diese Datei gehört in die Datensicherung,
nicht ins Git-Repository. Sie speichert Ziel-IDs und einen Fingerabdruck der
Anfrage, keine Zugangsdaten. Queue-Jobs speichern zusätzlich
`replacement_request_id`; das Feld bleibt bei Neustart und im Verlauf erhalten.

| Phase | Wiederholung derselben Anfrage |
| --- | --- |
| `deleting` | Stoppen: Löschabschluss unklar oder Löschung fehlgeschlagen; Bestand manuell prüfen. |
| `deleted` | Nur Abgleich und Queue-Aufnahme wiederholen. Niemals erneut löschen. |
| `queueing` | Bereits persistierten Job/Verlauf übernehmen. Ohne eindeutigen Beleg stoppen. |
| `queued` | Gespeicherte Erfolgsmeldung zurückgeben. Keine weitere Aktion. |

Ein unvollständiger Vorgang sperrt auch eine neue Anfrage-ID für dieselbe
TMDB-ID. Nach fehlgeschlagener/unterbrochener Löschung nicht durch wiederholte
Klicks oder pauschales Löschen des Journals fortsetzen. Administratoren müssen
die gespeicherten Ziel-IDs mit Jellyfin und den tatsächlichen Dateien abgleichen
und den Queue-Verlauf prüfen. Es gibt bewusst keine automatische erneute
Löschung bei unklarem Zustand. Nach Klärung kann der fehlende Film über den
gewöhnlichen Downloadweg geladen werden; ein blockierter Journaleintrag muss
für eine spätere Ersatzaktion gezielt administrativ bereinigt werden.

Die Anwendung verwendet bereits einen gemeinsamen Queue-Prozess. Innerhalb
dieses Prozesses serialisiert ein separater Lock Ersatzanfragen. Die Löschphase
verwendet dieselbe Lock-Reihenfolge wie automatische Queue-Aufnahmen. Das Journal
sperrt zusätzlich parallele unvollständige Ersatzvorgänge derselben Film-ID.

## Prüfung

Automatisierte Tests verwenden ausschließlich temporäre Journale und simulierte
Jellyfin-/Queue-Clients. Es werden keine echten Medien gelöscht.

```powershell
python -m pytest -q tests/test_movie_redownload.py tests/test_persistence_reliability.py tests/test_series_queue_circuit_breaker.py tests/test_movie_jellyfin_status.py tests/test_queue_jobs.py tests/test_api_security.py
```
