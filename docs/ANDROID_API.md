# Android- und Mobile-API

Stand: API-Version 1. Diese Dokumentation beschreibt zuerst den bestehenden `/api`-Vertrag und danach die additiv eingeführten `/api/v1`-Erweiterungen. Die Weboberfläche verwendet weiterhin die Legacy-Routen; gemeinsame Handler und Businesslogik verhindern zwei voneinander abweichende Backends.

## Grundregeln des bestehenden Servers

- FastAPI stellt JSON über `/api/...` und Live-Ereignisse über `/ws` bereit.
- Der Server verwaltet eine globale Queue und Watchlist für genau eine Instanz/einen Benutzer.
- Die Weboberfläche verwendet ausschließlich Web-Sitzungscookies (und auf Legacy-Routen weiterhin HTTP Basic). `/api/v1/...` akzeptiert ausschließlich Mobile-Bearer-Sitzungen. Mobile-Bearer bleiben nur auf den expliziten Legacy-Kernaliasen zulässig, damit ältere App-Versionen weiter funktionieren; administrative Web-Routen sind davon ausgeschlossen.
- Nicht initialisierte Installationen bleiben für den Setup-Assistenten offen.
- Fehler sind historisch nicht einheitlich:
  - Auth-Middleware: `{"detail":"Anmeldung erforderlich.","code":"auth_required"}`
  - `HTTPException`: `{"detail":"..."}`
  - Validierung: `{"detail":[...]}` mit Status 422
  - unerwarteter Fehler: `{"error":"Interner Serverfehler."}` mit Status 500; Details stehen nur im Serverlog
- Erfolgreiche Mutationen antworten derzeit mit Status 200, auch wenn Folgearbeit asynchron läuft.
- Zeitstempel sind Unix-Sekunden als `float`.

## Legacy-Authentifizierung

`GET /api/auth/status` ist öffentlich und liefert:

```json
{
  "configured": true,
  "required": true,
  "authenticated": false,
  "username": "",
  "source": "settings",
  "setup_required": false,
  "prompt_setup": false,
  "min_password_length": 8,
  "min_username_length": 3
}
```

`POST /api/auth/login` erwartet `{username,password}` und setzt bei Erfolg das HttpOnly-Cookie `royal_session`. Die serverseitige Sitzung läuft spätestens nach 30 Tagen oder 14 Tagen Inaktivität ab. `POST /api/auth/logout` widerruft das Cookie. HTTP Basic bleibt für bestehende Skripte verfügbar.

## Discovery und Details

### Filme

```text
GET /api/genres
→ {genres:string[]}

GET /api/movies?mode=search|new|top|genre&query=&genre=&page=1
→ {results,category,page,has_more,last_page_full,sources}
```

`page` liegt zwischen 1 und 50. Katalogseiten enthalten 32 Einträge; die Größe ist noch kein explizites Vertragsfeld. Ein Film-Treffer enthält:

```text
title, slug, url, year, is_movie, provider,
content_language, cover_url, in_jellyfin?
```

`in_jellyfin` fehlt, wenn Jellyfin nicht konfiguriert oder nicht verfügbar ist. Katalogquellen haben die Form:

```text
{key,label,content_language,language_label,count}
```

Die freie Filmsuche liefert `category:null`, `has_more:false` und `sources:[]`.

```text
GET /api/movie/{slug:path}
```

Basisantwort:

```text
title, url, year, runtime, cover_url, description, genres,
provider, provider_label, content_language, language_label,
hosters[{name,url,language,quality}],
hoster_label, hoster_route, hoster_score, hoster_fallback_count,
metadata_source
```

Bei TMDB-Treffer können zusätzlich vorhanden sein:

```text
tmdb_id, backdrop_url, original_title, release_date, rating, vote_count,
tagline, certification, certification_country, status, original_language,
spoken_languages, countries, directors, writers,
cast[{name,character,profile_url}], production_companies, keywords,
collection, budget, revenue, trailer, tmdb_url
```

Das Detail wiederholt den zum Aufruf verwendeten `slug` nicht. Der Client muss ihn aus dem Katalogzustand behalten.

```text
POST /api/movies/preload {slugs:string[]}
→ {movies:{[slug]:MovieDetail}}

POST /api/tmdb/movie {slug,title,year,tmdb_id?}
→ {movie:object|null}

POST /api/tmdb/movies {items:[{slug,title,year,tmdb_id?}]}
→ {movies:{[slug]:MovieMetadata}}

POST /api/jellyfin/matches {items:[...]}
→ {matches:{[slug]:boolean}}
```

TMDB-/Jellyfin-Batches verarbeiten höchstens 100 Elemente. Die TMDB-Endpunkte nutzen aktuell Titel/Jahr; das optionale `tmdb_id` wird dort noch nicht zur direkten Abfrage verwendet.

### Serien

```text
GET /api/series?mode=search|discover|new|trending|alpha&query=&letter=&page=1
→ {results,direct_series,mode,page,has_more,last_page_full,sources}
```

Serientreffer:

```text
title, base_slug, sample_slug, sample_url, year, cover_url,
provider, provider_label, content_language, language_label,
sources[{key,label,content_language}]
```

Providerübergreifend erkannte gleiche Serien werden gruppiert. Bei einer direkt eingegebenen URL kann `direct_series` bereits ein vorläufiges Detail enthalten.

```text
POST /api/series/load
{
  "sample_slug":"...",
  "base_slug":"...",
  "refresh_jellyfin":false,
  "defer_checks":false
}
```

Serien-Detail:

```text
title, base_slug, url, cover_url, description, genres,
provider, provider_label, content_language, language_label,
episode_count, watchlisted,
availability_pending, enrichment_pending,
jellyfin_configured, jellyfin_pending, jellyfin_available:boolean|null,
watch_mode, cleanup_mode, metadata_source,
tmdb_id?, aliases?, season_episode_counts?, season_counts_checked_at?,
year?, runtime?,
seasons[{season,episodes[{
  season,episode,slug,url,release_name,
  queued,downloaded,in_jellyfin,unreleased
}]}]
```

`defer_checks=true` liefert schnell die Providerstruktur. In diesem Zustand müssen Clients `availability_pending` beachten und dürfen anfängliche `false`-Werte nicht als abschließenden Bestand interpretieren.

Für den schnellen Jellyfin-Abgleich einer bereits geöffneten Serie gibt es einen
gezielten Endpunkt. Er lädt ausschließlich Episoden der eindeutig zugeordneten
Jellyfin-Serie und blockiert daher nicht auf dem vollständigen Episodenindex:

```text
POST /api/series/jellyfin-status
{
  "title":"House of the Dragon",
  "tmdb_id":94997,
  "aliases":[],
  "episodes":[{"slug":"...","season":1,"episode":1}],
  "force":false
}
→ {
  "configured":true,
  "available":true,
  "stale":false,
  "checked_at":1785592800.0,
  "episodes":{"...":true},
  "count":1
}
```

`available=false` bedeutet, dass kein aktueller, verlässlicher Jellyfin-Abruf
möglich war. Falls ein letzter erfolgreicher Stand existiert, wird er mit
`stale=true` zurückgegeben. Clients dürfen einen veralteten Stand anzeigen,
aber nicht als Freigabe für einen erneuten Download verwenden. `force=true`
umgeht den kurzlebigen Detailcache.

### Anime

```text
GET /api/anime?mode=search|latest|popular|trending&query=&page=1
→ {results,mode,page,has_more,total,disabled,disabled_reason?}
```

Anime-Treffer:

```text
id,title,media_type,year,cover_url,banner_url,description,genres,
rating,translations:{dub?:int,sub?:int,raw?:int},
provider,content_language,episode_count
```

```text
GET /api/anime/{anime_id}?translation=dub|sub|raw&episode_page=1
```

Das Detail ergänzt:

```text
translation, translation_labels,
page, page_count, page_size, total,
episodes[{number,label,slug,queued,downloaded}]
```

Anime verwendet derzeit MKissa und besitzt keine Watchlist-/Jellyfin-Verknüpfung.

### Bilder

`GET /api/cover?url=<öffentliche-http(s)-url>` proxyt Providerbilder für die Web-Sitzung mit maximal 10 MiB. Die Mobile-Entsprechung ist `GET /api/v1/cover?...` mit Bearer-Authentifizierung. Private, lokale, credentialbehaftete Ziele, private DNS-Ergebnisse und unsichere Redirects werden als SSRF-Schutz abgewiesen. TMDB-Bilder kann der Client direkt über HTTPS laden. Native Clients senden den Bearer ausschließlich an den RoyalDownloader-Ursprung; der Server ergänzt Provider-Header und Referer. Der In-Memory-Cache ist auf 64 MiB begrenzt.

## Queue und Download

```text
GET /api/queue
→ {queue:{count,jobs[],groups[]}}
```

Queue-Snapshot:

```json
{
  "count": 1,
  "groups": [{
    "name": "Filme",
    "items": [{
      "slug": "...",
      "job_id": "a persistent opaque ID",
      "title": "...",
      "hoster_label": "VOE",
      "provider": "filmpalast",
      "content_language": "de",
      "done": false
    }]
  }]
}
```

```text
POST /api/queue/add    {slugs:string[]}
→ {added,skipped,skipped_details,auto_started,done_jobs,total_jobs,queue}

POST /api/queue/remove {slug:string}
→ {removed,cancelled,queue}

POST /api/queue/clear  {}
→ {removed,queue}

POST /api/download/cancel {}
→ {cancelled:true,queue}
```

`queue/add` löst Providerdaten auf und startet akzeptierte Einträge automatisch. `queue/clear` entfernt wartende Einträge; `/download/cancel` bricht den gesamten Lauf ab.

Die neuen Job-Verträge sind unter `/api` und `/api/v1` identisch verfügbar:

```text
GET  /queue/jobs
GET  /queue/history
POST /queue/jobs/{job_id}/cancel
POST /queue/jobs/{job_id}/retry
POST /queue/jobs/{job_id}/move    {direction:"up"|"down"}
POST /queue/jobs/{job_id}/resume
```

Asynchron akzeptierte Aktionen antworten mit `202`. Ein Job enthält mindestens
`job_id`, `media_type`, `title`, `slug`, `provider`, `hoster`, `quality`,
`content_language`, `status`, Zeitstempel, Fortschritt, Byte-Zähler,
Geschwindigkeit, ETA, Fehler, Versuche, Retry-Zeitpunkt und finalen Pfad.
Terminale Jobs bleiben in einer persistenten Historie der letzten 500 Jobs.
Laufende Downloads können mit der gegenwärtigen Engine nicht sicher pausiert
werden; `/pause` meldet deshalb explizit `running_pause_not_supported` statt
einen Scheinzustand zu speichern.

## Watchlist und Serienautomatisierung

```text
GET  /api/watchlist
POST /api/watchlist/add
POST /api/watchlist/mode
POST /api/watchlist/remove
POST /api/watchlist/check
POST /api/watchlist/open
```

Add-Payload:

```text
base_slug, title, sample_url, known_slugs[],
download_mode, cleanup_mode?, tmdb_id?, aliases?,
season_episode_counts?, season_counts_checked_at
```

Modi:

```text
download_mode: all | latest_season | next_season
cleanup_mode:  keep | watched_seasons | watched_episodes
```

Mode-Payload: `{base_slug,download_mode,cleanup_mode?}`. Remove verwendet `{base_slugs:string[]}`, Check `{base_slugs:string[]|null}`, Open `{base_slug}`.

Antworten enthalten `{watchlist:[...]}`. Ein Eintrag besitzt neben den gespeicherten Serien-/TMDB-Feldern diese abgeleiteten Mobilfelder:

```text
download_mode_label, cleanup_mode_label,
download_mode_ready, cleanup_mode_ready,
new_count, queued_count, failed_count,
status: blocked|failed|queued|waiting_window|missing|current
```

`failed_downloads` ist eine Map `slug → {message,attempts,next_retry}`. `watchlist/open` liefert ein Serien-Detail und zusätzlich `preselect_slugs[]`. Add und Mode können nach der unmittelbaren Antwort asynchron weiterprüfen; das endgültige Ergebnis folgt über WebSocket.

## Geräteübergreifendes Geschmacksprofil

Web-, Android- und Automationsclients teilen sich ein serverseitiges Profil.
Alle Routen existieren sowohl unter `/api/taste/...` als auch unter
`/api/v1/taste/...`; sie unterliegen derselben Anmeldung wie die übrige API.

```text
GET  /api/v1/taste/profile
POST /api/v1/taste/events
POST /api/v1/taste/feedback
POST /api/v1/taste/import
POST /api/v1/taste/reset
```

Ein Ereignis verwendet:

```json
{
  "action": "open",
  "source": "android",
  "media_type": "movie",
  "item_key": "movie:provider-slug",
  "title": "Titel",
  "metadata": {
    "genres": ["Science-Fiction"],
    "tags": ["Weltraum"],
    "studios": ["Studio"],
    "directors": ["Name"],
    "actors": ["Name"],
    "languages": ["de"],
    "year": 2024,
    "runtime": 118
  }
}
```

Unterstützte Aktionen sind `search`, `open`, `download`, `watchlist`,
`subscription`, `watch_complete`, `favorite`, `like`, `dislike`, `dismiss`,
`remove` und `rating`. Für `rating` steht die Zahl von 0 bis 10 in `value`.
Stabile Schlüssel sind `movie:<slug-or-tmdb-id>`, `series:<base-slug-or-tmdb-id>`
und `anime:<id>`. Wiederholte Downloads derselben Serie werden serverseitig
gedrosselt, damit eine Staffel das Profil nicht künstlich dominiert.

Explizites Feedback verwendet denselben Inhalt plus `action:like|dislike|dismiss|favorite|rating`.
`action:clear` entfernt die explizite Entscheidung. Die Profilantwort enthält
nur aggregierte `dimensions`, `favorites`, `recent` mit sicheren Schlüsseln,
`blocked_items`, `item_feedback`, Zähler und Zeitstempel. Suchbegriffe, Titel
und die vollständige Ereignishistorie werden nicht an Clients zurückgegeben.

`taste/import` ist ausschließlich für die einmalige Übernahme des früheren
Browserprofils vorgesehen und akzeptiert `{genres:{...},kinds:{...}}`.
`taste/reset` löscht Ereignisse, Feedback, Jellyfin-Snapshot und Legacy-Import.

## TMDB, Jellyfin und Providerkonfiguration

Für die App relevante Lese-/Batch-Endpunkte:

```text
POST /api/tmdb/movie
POST /api/tmdb/movies
POST /api/jellyfin/matches
GET  /api/providers/config
```

Providerkonfiguration:

```text
movies[], series[], anime[],
enabled_movies[], enabled_series[], enabled_anime[],
labels:{provider:label},
catalog:{provider:{
  key,label,content_language,media_types[],language_label,homepage
}},
content_languages[], languages:{code:label}, saved
```

Administrative Schreibendpunkte für Provider-, Jellyfin- und TMDB-Konfiguration bleiben primär Aufgabe der Weboberfläche. API-Schlüssel werden von GET-Antworten nicht zurückgegeben.

## Legacy-WebSocket `/ws`

Authentifizierung wird beim Handshake und anschließend spätestens alle 30 Sekunden geprüft. Ohne gültige Sitzung schließt der Server mit Code 1008. Es gibt keinen initialen Snapshot und kein Replay.

| `type` | Payload |
|---|---|
| `log` | `{message,level}` |
| `progress` | `{label,msg,pct?}`; `pct` fehlt bei unbekanntem Wert |
| `queue_started` | `{added,done_jobs,total_jobs,queue}` |
| `queue_update` | `{queue}` |
| `job_done` | `{ok,label,slug,msg,done_jobs,total_jobs,successful_jobs,failed_jobs,active,pending}` |
| `queue_done` | `{done_jobs,total_jobs,successful_jobs,failed_jobs}` |
| `watchlist_update` | `{watchlist}` |
| `jellyfin_update` | `{watchlist}` |
| `updater_install` | `{installer}` |
| `updater_config` | `{config}` |

Die Updater-Konfiguration enthält additiv `update_channel` und den daraus
abgeleiteten `update_branch`. Erlaubt sind `stable` → `main` und `overnight` →
`overnight`; fehlende Werte bedeuten rückwärtskompatibel Stable. Der
Update-Status kennzeichnet einen erkannten Rückwechsel zu einem älteren oder
divergierten Stable-Stand mit `possible_downgrade` und
`channel_switch_requires_confirmation`. `POST /api/updater/install` akzeptiert
dafür additiv `confirm_channel_switch`; ältere Clients bleiben für normale
Updates unverändert funktionsfähig.

Für Overnight kommen additiv `quality_gate` und `quality_approved` hinzu; ein
Commit bleibt bei fehlender, laufender oder fehlgeschlagener Quality-Prüfung
nicht installierbar.

Die Events besitzen keine Event-ID, Sequenz oder Replay-Funktion. `progress` enthält keine Job-ID. Legacy-Clients müssen nach jedem Connect `GET /api/queue` und `GET /api/watchlist` nachladen.

## Additive API v1

v1 ersetzt keine Legacy-Route. Kernrouten sind zusätzliche Dekoratoren auf denselben Handlern und liefern deshalb bewusst dieselben DTOs und Statuscodes. Die stabilen Neuerungen betreffen Kompatibilitätsaushandlung, Bearer-Login und initiale Live-Synchronisierung.

### Capabilities und Health

`GET /api/v1/capabilities` ist öffentlich:

```json
{
  "name": "Royal Downloader",
  "application_version": "1.0.0-rc.3",
  "update_channels": {"stable": "main", "overnight": "overnight"},
  "api_version": 1,
  "supported_api_versions": [1],
  "minimum_api_version": 1,
  "build": "abcdef123456",
  "initialized": true,
  "setup_required": false,
  "authentication": {
    "configured": true,
    "required": true,
    "methods": ["bearer"],
    "legacy_methods": ["cookie", "basic"],
    "token_ttl_seconds": 2592000,
    "token_idle_timeout_seconds": 1209600
  },
  "features": {
    "movies": true,
    "series": true,
    "anime": true,
    "queue": true,
    "watchlist": true,
    "jellyfin_matching": true,
    "tmdb_metadata": true,
    "cover_proxy": true,
    "websocket": true
  },
  "websocket": {
    "path": "/api/v1/ws",
    "legacy_path": "/ws",
    "event_schema_version": 1,
    "initial_snapshot": true,
    "authorization_header": true,
    "authentication": ["bearer"]
  }
}
```

`application_version` bezeichnet die veröffentlichte Anwendungsversion; `build`
bezeichnet davon getrennt die konkrete Commit-Revision und kann `null` sein.
Beide Felder sind additiv. `GET /api/v1/health` liefert öffentlich weiterhin nur
`{status:"ok",api_version:1}` und offenbart keine Queue-Zähler.

### Bearer-Sitzung

```text
GET /api/v1/auth/status
```

Erweitert den Legacy-Status um:

```text
api_version, auth_method:none|bearer|cookie|basic,
token_ttl_seconds, token_idle_timeout_seconds
```

```text
POST /api/v1/auth/login
{username,password,device_label}
```

Erfolg ergänzt den Auth-Status um:

```text
access_token, token_type:"Bearer", expires_in,
idle_timeout_seconds, device_label, api_version, auth_method:"bearer"
```

Die Antwort trägt `Cache-Control: no-store` und setzt kein Cookie. Danach:

```http
Authorization: Bearer <access_token>
```

Das Token ist opaque. Auf dem Server wird nur sein SHA-256-Fingerprint gespeichert. Mobile- und Web-Sitzungen haben getrennte Typen und können nicht gegenseitig verwendet oder widerrufen werden. `POST /api/v1/auth/logout` widerruft ausschließlich das aktuelle Mobile-Bearer-Token. `POST /api/v1/auth/sessions/revoke` widerruft ausschließlich andere Mobile-Sitzungen und bewahrt die aufrufende Sitzung. Die entsprechenden `/api/auth/...`-Routen arbeiten nur mit Web-Sitzungen.

Sitzungen werden atomar persistiert. Schlägt das Speichern beim Erstellen oder Widerrufen fehl, antwortet der Server mit 503 und übernimmt die Änderung nicht in einen Zustand, der nach einem Neustart alte Tokens wiederbeleben könnte. Alte Sitzungsdatensätze ohne Typ werden aus Sicherheitsgründen als Web-Sitzungen behandelt; bereits vor dieser Trennung ausgegebene Mobile-Tokens erfordern daher eine erneute Anmeldung.

### v1-Kernaliase

| v1 | Entsprechende Legacy-Route |
|---|---|
| `GET /api/v1/genres` | `/api/genres` |
| `GET /api/v1/movies` | `/api/movies` |
| `GET /api/v1/movie/{slug:path}` | `/api/movie/{slug:path}` |
| `POST /api/v1/movies/preload` | `/api/movies/preload` |
| `POST /api/v1/tmdb/movie` | `/api/tmdb/movie` |
| `POST /api/v1/tmdb/movies` | `/api/tmdb/movies` |
| `POST /api/v1/jellyfin/matches` | `/api/jellyfin/matches` |
| `GET /api/v1/series` | `/api/series` |
| `POST /api/v1/series/load` | `/api/series/load` |
| `POST /api/v1/series/jellyfin-status` | `/api/series/jellyfin-status` |
| `GET /api/v1/anime` | `/api/anime` |
| `GET /api/v1/anime/{anime_id}` | `/api/anime/{anime_id}` |
| `GET /api/v1/cover` | `/api/cover` |
| `GET /api/v1/queue` | `/api/queue` |
| `POST /api/v1/queue/add` | `/api/queue/add` |
| `POST /api/v1/queue/remove` | `/api/queue/remove` |
| `POST /api/v1/queue/clear` | `/api/queue/clear` |
| `POST /api/v1/download/cancel` | `/api/download/cancel` |
| `GET /api/v1/watchlist` | `/api/watchlist` |
| `POST /api/v1/watchlist/add` | `/api/watchlist/add` |
| `POST /api/v1/watchlist/mode` | `/api/watchlist/mode` |
| `POST /api/v1/watchlist/remove` | `/api/watchlist/remove` |
| `POST /api/v1/watchlist/check` | `/api/watchlist/check` |
| `POST /api/v1/watchlist/open` | `/api/watchlist/open` |
| `GET /api/v1/taste/profile` | `/api/taste/profile` |
| `POST /api/v1/taste/events` | `/api/taste/events` |
| `POST /api/v1/taste/feedback` | `/api/taste/feedback` |
| `POST /api/v1/taste/import` | `/api/taste/import` |
| `POST /api/v1/taste/reset` | `/api/taste/reset` |

### v1-WebSocket

`/api/v1/ws` akzeptiert ausschließlich den Bearer-Header und sendet garantiert als erste Nachricht direkt nach dem Handshake:

```json
{
  "type": "snapshot",
  "api_version": 1,
  "event_schema_version": 1,
  "timestamp": 1785250800.0,
  "queue": {"count": 0, "groups": []},
  "watchlist": [],
  "download": {
    "done_jobs": 0,
    "total_jobs": 0,
    "successful_jobs": 0,
    "failed_jobs": 0,
    "active": 0,
    "pending": 0
  }
}
```

Danach folgen dieselben Events wie über `/ws`. Bei jedem Reconnect ersetzt der neue Snapshot den lokalen Queue-/Watchlist-Zustand; ältere lokale Events dürfen nicht darübergelegt werden. Widerrufene oder abgelaufene Sitzungen werden spätestens bei der nächsten 30-Sekunden-Prüfung mit Code 1008 getrennt.

## Fallback-Entscheidung für Android

1. Serveradresse normalisieren; nur HTTPS akzeptieren.
2. `GET /api/v1/capabilities` aufrufen.
3. Bei erfolgreicher Antwort prüfen, ob `supported_api_versions` Version 1 enthält und `minimum_api_version <= 1` gilt.
4. Dann v1-Login, v1-Kernrouten und den vom Server gemeldeten WebSocket-Pfad verwenden.
5. Bei 404 sowie bei 401/403 einer älteren globalen Auth-Middleware genau einmal den öffentlichen Legacy-Endpunkt `/api/auth/status` als Server-Fingerprint prüfen. Nur wenn dort ein gültiger RoyalDownloader-Status zurückkommt, auf Legacy wechseln.
6. Netzwerk-, DNS-, TLS-, Timeout-, Cloudflare-52x-, sonstige 5xx- oder JSON-Fehler sind kein Beleg für einen Legacy-Server und dürfen keinen stillen Downgrade auslösen.
7. Ein 401 einer geschützten Route bedeutet `Sitzung abgelaufen` beziehungsweise `Anmeldung erforderlich`: lokale Mobile-Zugangsdaten löschen, den Login-Zustand zeigen und schreibende Requests nicht automatisch wiederholen. 401 darf nie als Offline- oder Erreichbarkeitsfehler erscheinen.
8. 403, 404 ohne erfolgreichen Legacy-Fingerprint, 429, Wartungsantworten und inkompatible API-/Event-Schemaversionen bleiben eigenständige Fehlerklassen. Ein WebSocket-Abbruch löst einen begrenzten Reconnect mit anschließendem REST-Snapshot aus, ohne ihn als Geräte-Offlinezustand umzudeuten.

## Noch nicht durch v1 gelöste Vertragsgrenzen

- Kernantworten besitzen noch keine FastAPI-`response_model`-DTOs.
- Provider-Slugs sind öffentliche IDs und nicht langfristig stabil.
- Watchlist-Antworten enthalten interne Persistenzfelder und freie Fehlertexte.
- Fach- und Validierungsfehler besitzen noch nicht durchgängig einheitliche maschinenlesbare Codes; Authentifizierungsfehler unterscheiden mindestens `auth_required` und `session_expired`.
- v1-Events haben nach dem Snapshot keine Event-ID, Sequenz oder Replay-Funktion.
- WebSocket-Widerrufe wirken periodisch innerhalb von 30 Sekunden, nicht unmittelbar ereignisgetrieben.
- TMDB-/Jellyfin-Zustände unterscheiden nicht überall zuverlässig `false`, `unbekannt`, `nicht konfiguriert` und `nicht erreichbar`.
- Es gibt keine Idempotency-Keys für Queue-/Watchlist-Mutationen.

Diese Punkte können später innerhalb neuer DTO-/Event-Schemaversionen additiv verbessert werden. Die Android-App darf deshalb keine Rohfehlermeldungen oder Providerdetails als stabile Geschäftslogik interpretieren.
