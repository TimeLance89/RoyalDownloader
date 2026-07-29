# Royal Downloader für Android

Native Android-App für den bestehenden Royal-Downloader-Server. Die App lädt selbst keine Medien herunter: Provider, Extraktion, Queue, Automatisierung, TMDB und Jellyfin bleiben vollständig auf dem Server.

Standardserver: `https://royal-downloader.de/`

## Technische Basis

- Kotlin, Coroutines und `StateFlow`
- Jetpack Compose und Material 3
- Navigation Compose und ViewModels
- Retrofit mit Kotlin Serialization
- OkHttp für HTTPS und WebSocket
- Coil für Poster und Backdrops
- Preferences DataStore für nicht sensible Einstellungen
- Android Keystore plus AES-GCM für das Sitzungstoken
- Mindestversion Android 8.0 / API 26
- Target SDK 36, JDK 17, AGP 9.2.1

## Architektur

```text
Compose-Screens
    ↓ UI-Aktionen / UiState
ViewModels
    ↓
Repository
    ├─ REST-Client (v1 oder Legacy)
    ├─ WebSocket-Client mit Reconnect und Snapshot-Resync
    ├─ SecureTokenStore
    └─ AppPreferences
        ↓
Royal Downloader FastAPI → Provider / Queue / TMDB / Jellyfin
```

Die UI kennt keine Provider- oder Downloadimplementierung. Netzwerkmodelle werden zentral tolerant deserialisiert, weil der Legacy-Server optionale Felder je nach TMDB-/Jellyfin-Zustand auslassen kann. Der Servermodus (`v1` oder `legacy`) wird beim Verbindungsaufbau bestimmt und gilt anschließend für REST und WebSocket gemeinsam.

## Server-Kompatibilität

### Bevorzugt: API v1

Beim Start ruft die App `GET /api/v1/capabilities` auf. Unterstützt der Server API-Version 1, verwendet sie:

- `Authorization: Bearer <token>` für geschützte REST-Aufrufe
- `/api/v1/...` für Filme, Serien, Anime, Queue und Watchlist
- `/api/v1/ws` für Live-Ereignisse
- den initialen WebSocket-Snapshot zur Synchronisierung nach Connect/Reconnect

Login erfolgt über `POST /api/v1/auth/login`. Das zurückgegebene opaque Token ist serverseitig widerrufbar und wird nur verschlüsselt auf dem Gerät gespeichert.

### Legacy-Fallback

Antwortet der Capabilities-Endpunkt mit 404 oder ist v1 nicht verfügbar, kann die App auf die bestehenden `/api/...`-Routen und `/ws` zurückfallen. Der Fallback ist für ältere Royal-Downloader-Installationen gedacht und bildet denselben fachlichen Funktionsumfang ab. Einschränkungen:

- keine Versions- oder Feature-Aushandlung
- kein initialer WebSocket-Snapshot
- Authentifizierung nur über die vom Legacy-Server angebotene Cookie-/Basic-Kompatibilität
- geringere Unterscheidbarkeit zwischen nicht konfigurierten und nicht erreichbaren Diensten

Zugangsdaten werden auch im Legacy-Modus nicht dauerhaft gespeichert. Für den vollständigen sicheren Mobilbetrieb sollte der Server auf einen Stand mit API v1 aktualisiert werden.

Der detaillierte Vertrag steht in [`../docs/ANDROID_API.md`](../docs/ANDROID_API.md).

## Screens und Funktionen

- Verbindungsprüfung mit Zuständen für offline, Authentifizierung, inkompatible API und Serverfehler
- Wartungsstatus und serverseitige Feature-Flags werden ausgewertet
- Öffentlich erreichbare Server ohne eingerichtetes Konto werden bis zum Sicherheitssetup blockiert
- Login mit automatisch gesetzter Gerätebezeichnung und widerrufbarer Sitzung
- Home mit neuen und Top-Filmen, Trending-Serien, neuen Anime sowie Queue-/Watchlist-Status
- Discovery mit paginierten Standardfeeds und Suche für Filme, Serien und Anime
- Native Film-, Serien- und Anime-Details inklusive paginierter Anime-Episoden
- Staffel-/Episodenauswahl inklusive Queue-, Download-, Release- und Jellyfin-Status
- Queue-Snapshot, Live-Fortschritt, Ergebnisse/Fehler der laufenden App-Sitzung, Entfernen einzelner Einträge und globaler Abbruch
- Serienabonnements mit Prüfstatus, Abo-Regel, Aktualisieren und Entfernen
- Serveradresse, API-Information und Logout in den Einstellungen
- Fehler-, Leer-, Lade- und Reconnect-Zustände ohne WebView

Seltene administrative Einstellungen wie Serverpfade, Providerreihenfolge, TMDB-/Jellyfin-Schlüssel, Telegram, Seerr und Updater bleiben in der Weboberfläche.

## Sicherheit

- Es werden ausschließlich HTTPS-Serveradressen akzeptiert.
- Cleartext-Traffic ist in Manifest und Network Security Config deaktiviert.
- Das v1-Bearer-Token liegt in DataStore nur als AES-GCM-Chiffretext; der Schlüssel verbleibt im Android Keystore.
- App-Backups sind deaktiviert.
- Cloud-Backups und Geräteübertragungen schließen alle App-Datendomänen explizit aus.
- Passwörter, Tokens und Authorization-Header dürfen nicht geloggt werden.
- Logout widerruft die aktuelle Serversitzung und löscht die lokale Tokenkopie.
- HTTP-Redirects sind deaktiviert, damit Bearer- oder Legacy-Cookie-Tokens nie an ein anderes Ziel weitergereicht werden.
- Es gibt keine Cloudflare-, Provider-, TMDB- oder Jellyfin-Secrets in der APK.
- Zertifikat-Pinning wird bewusst nicht eingesetzt, damit Cloudflare-Zertifikatswechsel und selbst gehostete HTTPS-Instanzen ohne App-Update funktionieren.

Ein initialisierter Server ohne Konto ist über seine API vollständig offen. Die App zeigt deshalb ausschließlich das Sicherheitssetup, bis in der Weboberfläche ein Konto eingerichtet wurde.

## Setup und Build

Voraussetzungen:

- Android Studio mit Unterstützung für AGP 9.2
- JDK 17
- Android SDK 36.1 und Build Tools 36.0.0
- der mitgelieferte Gradle-9.4.1-Wrapper

Projekt in Android Studio öffnen:

```text
<Repository>/AndroidApp
```

Kommandozeile aus `AndroidApp/`:

```bash
./gradlew lintDebug
./gradlew lintRelease
./gradlew testDebugUnitTest
./gradlew assembleDebug
./gradlew assembleRelease
```

Unter Windows entsprechend `gradlew.bat` verwenden.

Die erzeugten APKs liegen danach unter:

```text
AndroidApp/app/build/outputs/apk/debug/app-debug.apk
AndroidApp/app/build/outputs/apk/release/app-release-unsigned.apk
```

Die Debug-App verwendet die Application-ID `de.royaldownloader.app.debug`. Der Standardserver wird über `BuildConfig.DEFAULT_SERVER_URL` gesetzt; eine später eingegebene Serveradresse wird normalisiert in DataStore gespeichert. Zugangsdaten oder Tokens gehören nie in Gradle-Dateien.

## Tests und CI

Der Android-Job in `.github/workflows/quality.yml` verwendet JDK 17 und Gradle 9.4.1 mit Gradle-Cache. Er führt getrennt aus:

```text
lintDebug
lintRelease
testDebugUnitTest
assembleDebug
assembleRelease
```

Die CI archiviert beide APKs sowie die zur Fehleranalyse benötigten R8-Mapping-Dateien. Das Release-APK ist minifiziert, aber absichtlich unsigniert.

Die JVM-Suite prüft DTO-Verträge, Login-/Mutation-Routen, ungültige Antworten, sichere Retry-Regeln, URL-Normalisierung, Provider-Pfadencoding und WebSocket-Backoff. Instrumentierte Compose-Tests benötigen zusätzlich einen Emulator oder ein Gerät und gehören deshalb nicht zum normalen Linux-CI-Job.

## Bekannte Grenzen

- Kataloge und Details werden nicht dauerhaft offline gespeichert; ohne Server sind nur Verbindungs-/Fehlerzustände verfügbar.
- Downloads laufen auf dem Server. Androids DownloadManager wird nicht verwendet.
- Die bestehende Queue besitzt keine stabilen Job-IDs, keine persistierte Abschluss-Historie und keinen REST-Fortschritt mit Bytes, Geschwindigkeit oder ETA.
- v1 versioniert Transport, Login und Kompatibilität, übernimmt für die Kernfunktionen aber bewusst die bestehenden Legacy-DTOs.
- Nach dem initialen v1-Snapshot verwenden Live-Ereignisse weiterhin die bestehenden Eventformen. Es gibt noch keine Event-IDs oder Replay-Funktion.
- Provider-Slugs bleiben im aktuellen Kernvertrag sichtbar und können nicht als dauerhaft stabile Medien-ID betrachtet werden.
- TMDB- und Jellyfin-Ausfälle führen teilweise zu fehlenden statt ausdrücklich als unbekannt markierten Feldern.
- Keine Push-Benachrichtigungen und kein garantierter Livebetrieb bei vollständig beendeter App.
- HTTP-Fehler von Cloudflare können HTML statt JSON enthalten; die App behandelt sie als Gateway-/Verbindungsfehler.
- Eine produktive Release-Signierung ist nicht im Repository hinterlegt und muss über einen geschützten Keystore in der eigenen Build-/Release-Pipeline erfolgen.
