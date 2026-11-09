# Jellyfin: Intro- und Abspannmarkierungen

## Umfang

RD liest vorhandene Jellyfin-Metadaten. Die Erkennung bleibt vollständig in
Jellyfin bzw. Intro Skipper. Es gibt keine Medienanalyse, Dateizugriffe auf
Videos, Hintergrundscans, neuen Abhängigkeiten oder Client-Änderungen in RD.
TV-App, Player, Nächste-Folge-Karte und bestehende Zeitregeln bleiben unverändert.

## Jellyfin-Schnittstellen und Kompatibilität

Der bestehende `JellyfinClient` verwendet seinen vorhandenen JSON-Transport
und `jellyfin_auth_headers`: `Authorization: MediaBrowser Token="…"`.
Zugangsdaten bleiben serverseitig; Redirects werden nicht verfolgt. Alle
Anfragen haben einen Socket-Timeout von fünf Sekunden und laufen in den
FastAPI-Workerthreads, nicht im asynchronen Hauptthread.

| Jellyfin-Endpunkt | Verwendung |
| --- | --- |
| `GET /Users/{profileId}` | Verknüpftes Profil prüfen; deaktivierte Profile und Profile ohne Wiedergaberecht abweisen. |
| `GET /Items?UserId={profileId}&Ids={itemId}&IncludeItemTypes=Movie,Episode&Recursive=true&Limit=1&EnableImages=false&EnableUserData=false&ExcludeLocationTypes=Virtual,Offline&IsMissing=false&IsPlaceHolder=false` | Sichtbarkeit des exakten Films bzw. der exakten Episode prüfen und Laufzeit lesen. |
| `GET /MediaSegments/{itemId}?includeSegmentTypes=Intro,Outro` | Vorhandene Intro-/Outro-Markierungen lesen. |

Jellyfin Media Segments existiert seit 10.10. Die DTO-Felder `ItemId`, `Type`,
`StartTicks` und `EndTicks` stimmen in den überprüften 10.10- und aktuellen
Serverquellen überein. Die lokale Verbindung wurde am 09.11.2026 lesend mit
Jellyfin **12.4.0** geprüft: Profilprüfung, Inhaltszuordnung und Segmentabruf
funktionierten; das ausgewählte Video lieferte eine leere Segmentliste.
Dieser Test bestätigt keine bereits abgeschlossene Intro-Skipper-Analyse.

RD benötigt keine versionsabhängigen Intro-Skipper-Privatendpunkte und installiert
keine Plugins. Ein nicht vorhandener Core-Endpunkt (`404`, `405`, `501` nach
erfolgreicher Inhaltsprüfung) wird als `unsupported` gemeldet. Das kann eine
fehlende API/Proxy-Route oder einen inzwischen entfernten Inhalt bedeuten;
RD behauptet daraus nicht, dass das Plugin fehlt. Plex wird nicht unterstützt.

Quellen:

- [Jellyfin Media Segments](https://jellyfin.org/docs/general/server/metadata/media-segments/)
- [Jellyfin-Controller 10.10.7](https://github.com/jellyfin/jellyfin/blob/v10.10.7/Jellyfin.Api/Controllers/MediaSegmentsController.cs)
- [Aktueller Jellyfin-Controller](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/MediaSegmentsController.cs)
- [Segment-DTO](https://github.com/jellyfin/jellyfin/blob/master/MediaBrowser.Model/MediaSegments/MediaSegmentDto.cs)

## RD-API

Lesen:

```http
GET /api/media-center/items/{jellyfinItemId}/segments
GET /api/v1/media-center/items/{jellyfinItemId}/segments
```

Nach einer erneuten Jellyfin-Analyse den Cache dieser Zuordnung sofort ersetzen:

```http
POST /api/media-center/items/{jellyfinItemId}/segments/refresh
POST /api/v1/media-center/items/{jellyfinItemId}/segments/refresh
```

POST benötigt keinen Body und startet **keine Analyse**. Er liest Jellyfin erneut.
Die bestehenden Web-Sitzungen bzw. die Authentifizierung der versionierten API
gelten unverändert. Aktivierte RD-Mitglieder und Administratoren dürfen lesen;
ein sofortiger Refresh erfordert Administratorrechte. Die bestehenden Regeln
für Origin, CSRF und mobile Bearer-Tokens bleiben bestehen.

Es wird ausschließlich das mit dem aufrufenden RD-Konto verknüpfte Jellyfin-Profil
verwendet. Eine Ausnahme ist die bereits bestehende Zuordnung `admin-legacy` zum
konfigurierten Standardprofil. Andere Konten erhalten keinen Administrator-Fallback.
Anfragende können weder per Query noch per Body ein fremdes Profil auswählen.

Die Item-ID muss eine Jellyfin-UUID sein; RD liefert sie kanonisch als 32-stellige
Hex-ID zurück. Es findet keine unscharfe Titel- oder TMDB-Zuordnung statt.

Antwort mit Markierungen (`200`):

```json
{
  "media_id": "11111111111111111111111111111111",
  "available": true,
  "status": "available",
  "segments": [
    {"type": "Intro", "start_seconds": 0.0, "end_seconds": 92.0},
    {"type": "Outro", "start_seconds": 2450.0, "end_seconds": 2630.0}
  ]
}
```

Ohne Markierungen (`200`):

```json
{
  "media_id": "11111111111111111111111111111111",
  "available": false,
  "status": "empty",
  "segments": []
}
```

Ausfallbeispiel (`503`):

```json
{
  "media_id": "11111111111111111111111111111111",
  "available": false,
  "status": "unavailable",
  "segments": [],
  "error": {
    "code": "jellyfin_timeout",
    "message": "Jellyfin antwortet nicht rechtzeitig."
  }
}
```

| Zustand | HTTP | Antwort |
| --- | --- | --- |
| Eindeutige Markierungen | 200 | `status=available`, `available=true` |
| Ein Teil der Daten ist ungültig | 200 | `status=partial`, nur gültige Markierungen, `discarded_segments` |
| Kein Intro/Outro vorhanden | 200 | `status=empty`, `available=false` |
| Keine RD-Anmeldung / Konto deaktiviert | 401 | Bestehendes Auth-Fehlerformat; keine Segmentdaten |
| RD-Rolle unzulässig, Profil fehlt/deaktiviert, kein Wiedergaberecht oder Refresh ohne Adminrechte | 403 | Auth-/Profilfehler; keine Segmentdaten |
| Inhalt fehlt, ist nicht sichtbar oder kein verfügbarer Film/keine Episode | 404 | `media_not_found`; keine Segmentdaten |
| RD-Profil oder Verbindung während des Abrufs geändert | 409 | `detail.code=media_context_changed`; keine Segmentdaten |
| Ungültige Item-UUID | 422 | FastAPI-Validierungsfehler |
| Jellyfin-Zugangsdaten abgewiesen | 502 | `jellyfin_auth_failed`, nicht als leere Liste behandeln |
| Ungültige Antwort / ausschließlich ungültige Markierungen | 502 | `invalid_jellyfin_response` / `invalid_media_segments` |
| Jellyfin fehlt, ist ausgefallen oder meldet 429/5xx | 503 | `status=unavailable`, spezifischer Fehlercode |
| Core-Endpunkt oder Mediencenter nicht unterstützt | 503 | `status=unsupported`, spezifischer Fehlercode |
| Abruf ausgelastet oder Wartezeit überschritten | 503 | `segments_busy`, später erneut versuchen |

`available` bezeichnet vorhandene **validierte Markierungen**, nicht die allgemeine
Abspielbarkeit eines Videos. Alle HTTP-Antworten verwenden `Cache-Control: no-store`;
der unten beschriebene Cache liegt ausschließlich im RD-Serverprozess.

## Datenvalidierung

Intern bleiben Start und Ende unveränderte Integer-Ticks in unveränderlichen
`Segment`-Objekten. Die JSON-Antwort normalisiert mit `10.000.000 Ticks = 1 Sekunde`.
Zeitgrenzen werden nicht gerundet, verlängert oder auf eine vermutete Intro-Länge
gekürzt. JSON-Sekundenwerte unterliegen der üblichen Gleitkomma-Darstellung.

- Nur `Intro` und `Outro` werden ausgegeben. Andere Jellyfin-Typen werden ignoriert.
- Die `ItemId` jeder Markierung muss der angefragten UUID entsprechen.
- Integer-Ticks müssen nichtnegativ sein und in einen signierten 64-Bit-Wert passen.
  Bool, Float, NaN, Infinity und numerische Strings werden nicht umgedeutet.
- Es muss `start < end` gelten; bei bekannter Laufzeit darf `end` nicht darüber liegen.
  Eine fehlende Laufzeit erlaubt keine Prüfung gegen das Medienende.
- Identische Markierungen werden dedupliziert und chronologisch sortiert.
- Sich überschneidende Markierungen sowie ein Intro nach einem Outro werden auf
  beiden Seiten verworfen. Direkt aneinandergrenzende Segmente sind zulässig.
- Ungültige Einzelwerte werden gezählt. Bleiben gültige Segmente übrig, lautet der
  Zustand `partial`; sind ausschließlich ungültige Werte vorhanden, ist es ein Fehler.
- Antworten über 256 Einträge oder mit widersprüchlichem `TotalRecordCount` werden
  als Fehler abgewiesen. Es gibt keinen stillen Teilabruf.

## Cache und Ressourcen

Der Cache ist pro Router/Serverprozess lokal, auf 1.024 LRU-Einträge begrenzt und
benötigt keine Dateien, Datenbankmigrationen, Timer oder Hintergrundjobs.

| Ergebnis | Gültigkeit |
| --- | --- |
| Valide/teilweise valide Markierungen | 300 Sekunden |
| Leere Liste | 30 Sekunden |
| Segment-Endpunkt nicht verfügbar | 60 Sekunden |
| Fehler beim Segmentabruf | 5 Sekunden |

Schlüssel enthalten Verbindung, einen Digest des API-Schlüssels, Konfigurations-
Generation, Jellyfin-Profil, Item-ID und aktuelle Laufzeit. Zugangsdaten werden
nicht im Klartext in Cache-Schlüsseln oder API-Fehlern veröffentlicht.

Profilsperre und Inhaltsberechtigungen werden **vor jeder Antwort** erneut in
Jellyfin geprüft, auch bei einem Cache-Treffer. Diese Berechtigungsdaten werden
nicht positiv gecacht. Ändern sich während des Abrufs das RD-Konto, die Rolle,
Verbindung oder Profilzuordnung, werden die vorbereiteten Daten nicht ausgeliefert.

Gleichzeitige Segmentabrufe desselben Schlüssels teilen ein `Future`. Andere Items
werden nicht durch einen globalen I/O-Lock blockiert. Maximal 16 unterschiedliche
Segmentabrufe laufen gleichzeitig; Mitwartende warten höchstens sieben Sekunden.
Die Profil-/Inhaltsprüfung erfolgt aus Sicherheitsgründen pro Anfrage und wird
nicht durch den Segmentcache übersprungen. Die Transport-Timeouts gelten pro
Socket-Operation; sie sind keine harte Gesamtlaufzeit für mehrere HTTP-Anfragen.

Ein Refresh verdrängt den bisherigen Snapshot. Gleichzeitige Abrufe teilen auch
diesen Refresh. Ein danach auftretender Fehler führt nicht zur Ausgabe alter
Skip-Ziele. Ohne expliziten Refresh wird ein noch gültiger Snapshot regulär bis
zum Ablauf seines TTL verwendet. Mehrere RD-Prozesse haben jeweils eigene Caches.

## Schritte auf dem NAS

1. Falls noch nicht installiert: In Jellyfin unter Dashboard → Plugins → Repositories die Quelle
   `https://intro-skipper.org/manifest.json` hinzufügen. Das Manifest liefert eine
   zur anfragenden Jellyfin-Version passende Plugin-Auswahl. Intro Skipper aus
   dem Katalog installieren und Jellyfin neu starten.
2. Die [Intro-Skipper-Installation](https://github.com/intro-skipper/intro-skipper/wiki/Installation)
   und die zu dieser Plugin-Version gehörenden FFmpeg-Anforderungen prüfen.
   In Dashboard → Geplante Aufgaben die Aufgabe **Detect and Analyze Media Segments**
   für die erste Analyse ausführen. Das kann auf dem NAS dauern und Ressourcen benötigen.
3. In Intro Skipper → Timestamps die erkannten Werte einer Serie/Folge bzw. eines
   Films prüfen. Falls Jellyfin diese noch nicht als Media Segments bereitstellt,
   die Aufgabe **Media segment scan** ausführen. Sie ist in der
   [Jellyfin-Anleitung](https://jellyfin.org/docs/general/server/metadata/media-segments/)
   beschrieben.
4. Den lokalen RD-Stand regulär installieren und RD neu starten. In RD das eigene
   Konto mit einem zugriffsberechtigten Jellyfin-Profil verknüpfen.
5. Eine tatsächlich vorhandene Jellyfin-Item-ID mit der GET-API prüfen. Nach einer
   erneuten Analyse als RD-Administrator den POST-Refresh aufrufen oder den TTL abwarten.

Die RD-Integration installiert selbst keine Jellyfin-Plugins und startet keine Medienanalyse.
Die Installation des optionalen File-Transformation-Plugins und Jellyfin-Web-UI-
Erweiterungen ist für diese RD-Backend-Schnittstelle nicht erforderlich.

Eine leere Core-Antwort unterscheidet nicht zwischen fehlendem Plugin, noch nicht
analysiertem Inhalt und tatsächlich fehlendem Intro/Outro. RD erfindet dafür keine
Zeitmarkierungen. Ein korrekt ausgelieferter Marker ist außerdem keine Garantie
für die inhaltliche Qualität der Plugin-Erkennung. Mehrere Medienfassungen unter
derselben Jellyfin-Item-ID sind nur so genau zuordenbar wie die Item-basierten
Jellyfin-Markierungen; RD erzeugt keine zusätzliche datei- oder fassungsspezifische Analyse.

## Prüfungen

Neue Tests: `tests/test_media_segments.py` und `tests/test_media_segments_api.py`.
Sie decken Normalisierung, widersprüchliche Daten, Client-Transport, RD- und
Jellyfin-Berechtigungen, Profil-/Serverwechsel, Refresh, TTL/LRU, Single Flight,
Lastbegrenzung, Timeout und Fehlerbehandlung ab. Relevante Bestandstests sind
`tests/test_movie_playback_stream.py` und `tests/test_plex_media_center.py`.

## Geänderte Dateien dieses Auftrags

| Datei | Änderung |
| --- | --- |
| `integrations/jellyfin_segments.py` | Neue Client-Methoden über den bestehenden JSON-/Auth-Transport. |
| `integrations/jellyfin_client.py` | Segment-Mixin in den bestehenden Client einbinden. |
| `application_services/media_segments.py` | Validierung, Fehlerzustände, Berechtigungen, TTL/LRU und Single Flight. |
| `api/api_media_segments_router.py` | Geschützte GET-/Refresh-Routen einschließlich v1-Aliassen. |
| `api/api_media_center_router.py` | Neue Routen registrieren. |
| `tests/test_media_segments.py` | Daten-, Transport- und Cache-Prüfungen. |
| `tests/test_media_segments_api.py` | API-, Profil-, Berechtigungs- und Kontextwechselprüfungen. |
| `docs/JELLYFIN_MEDIA_SEGMENTS.md` | Vertrag, Grenzen, Betrieb und NAS-Anleitung. |
