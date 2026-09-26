# RoyalDownloader Frontend-Architektur

## Aufbau und Einstieg

RoyalDownloader verwendet HTML, CSS und Vanilla JavaScript mit nativen ES Modules.
Es gibt keinen Bundler, keine neue Laufzeitabhängigkeit und keinen Build-Schritt.
`web/index.html` lädt ausschließlich `web/app.js` als Modul. Dieser Einstieg
initialisiert Übersetzung, Anmeldung, Setup und die Anwendung.

`web/js/composition.js` erzeugt die Feature-Dienste und verbindet sie durch
explizite Abhängigkeiten und Callbacks. `web/js/app.js` registriert Ansichten,
Sitzungsdienste und deren Lebensdauer. `web/js/shell/presentation.js` sowie
`shell/actions/` enthalten importierte Shell-Aktionen zwischen diesen Diensten.
Sie sind keine Browser-Globals. Die interne Registry `sharedPresentation` wird
nur von der Komposition und Shell benutzt; Feature-Module importieren sie nicht.
Neue Feature-Logik gehört in `features/`, nicht in die Registry oder Shell.

```text
web/
  index.html, app.js                 DOM-Shell und nativer Einstieg
  i18n.js                           inaktiver Update-Kompatibilitätsmarker
  js/
    composition.js                  Abhängigkeiten und Root-Elemente verbinden
    app.js                          Navigation und Sitzungslifecycle
    core/                           API, Store, WebSocket, Lifecycle, Fehler
    shell/                          importierte Shell-Aktionen und Queue-Abbild
    shared/components/              wiederverwendbare UI und Interaktion
    shared/formatters/, utils/       reine Formatierung und Hilfsfunktionen
    features/                       fachlich abgegrenzte Dienste und Ansichten
  style-tokens.css                   semantische Tokens und Theme-Aliase
  style.css                         geordneter CSS-Importbaum
  styles/                           Komponenten und Feature-Layouts
```

Die ursprüngliche Bestandsaufnahme bleibt unverändert in
[FRONTEND_AUDIT.md](FRONTEND_AUDIT.md) und [frontend-audit.json](frontend-audit.json).
Diese Dateien beschreiben bewusst den Zustand **vor** dem Umbau.

## Zustandsgrenzen

| Zustand | Eigentümer und Regeln |
| --- | --- |
| Benutzer, Sprache, Navigation, Verbindung | `core/store.js`; kleine unveränderliche Snapshots, abonnierbar mit Rückgabefunktion zum Abmelden |
| Queue und Downloadfortschritt | Server-Snapshots in der sitzungsweiten Queue-Ansicht; Shell-Abbild in `shell/state.js`, abgeleitete Slug-Menge für Statusanzeigen |
| Abos, Benachrichtigungen, Profil, Einstellungen | jeweilige Feature-Dienste; Server bleibt maßgeblich, Schreibantworten oder Live-Snapshots aktualisieren Ansichten |
| Kataloge und ausgewählte Medien | `discovery/movie-state.js`, `series-state.js` bzw. Anime-/AniWorld-Dienste; keine Einträge im globalen Store |
| Filter, Dialoge, Carousel-Position, Formulare | lokale Feature-Variablen; Formularentwürfe überschreiben sich nicht durch Hintergrundantworten |
| Home-Katalog und Empfehlungen | `home/data.js`, `cache.js`, weitere Home-Dienste; begrenzte Read-Caches und laufende Requests werden explizit verwaltet |

Persönliche Anfragen, Downloadjobs, Versuche und Medien bleiben fachlich getrennt.
Das Profil liest `/api/me/profile-summary` und dessen persistente persönliche
Historie. Eine geleerte Queue darf diese Historie nicht leeren. Die Bibliothek
liest ihren eigenen Serververtrag; Jellyfin-Medienverfügbarkeit ist kein
Integrations-Health-Signal. Regressionstests prüfen die unabhängige Historie.

## HTTP und Live-Daten

`core/api.js` ist der einzige normale HTTP-Transport. Er behandelt JSON,
Same-Origin-Cookies, Header, einheitliche `ApiError`-Objekte, Sessionablauf,
Timeouts und Abbruch. GET-Deduplizierung berücksichtigt die Request-Lebensdauer;
es gibt keinen unbeschränkten globalen Cache für persönliche Daten. Der
bestehende serverseitige Auth-/Origin-Vertrag wird erhalten.

```js
import { api } from "../../core/api.js";
const snapshot = await api.get("/api/queue", { signal: scope.signal });
await api.post("/api/example", payload, { signal: scope.signal });
```

Kein Feature ruft direkt `fetch` auf. Fachliche API-Dateien dürfen Endpunkte und
Payloads kapseln, verwenden dafür jedoch diesen Transport.

`core/websocket.js` besitzt die einzige Verbindung zu `/ws`, JSON-Verteilung,
Reconnect mit Backoff/Jitter und den Verbindungsstatus. Generationen verwerfen
Nachrichten alter Verbindungen. Close-Code 1008 beendet die Sitzung und stoppt
Reconnect. Das bestehende Protokoll hat keinen Anwendungs-Ping/Pong-Vertrag;
Protokoll-Heartbeats bleiben serverseitig.

```js
scope.add(websocket.subscribe("queue_update", message => {
  applySnapshot(message.queue);
}));
```

Ereignisnamen entsprechen den vorhandenen Backend-Verträgen, beispielsweise
`queue_update`, `download_progress`, `watchlist_update`,
`movie_subscriptions_update` und `updater_install`. Nach Reconnect werden
maßgebliche Snapshots erneut geladen. Feature-Code erzeugt keine eigenen Sockets.

## Lifecycle und Nebenwirkungen

Eine Ansicht implementiert `mount(root)`, `refresh()` und `unmount()` soweit sie
entsprechende Arbeit besitzt. Reine Formatierer benötigen keinen Lifecycle.
`core/navigation.js` beendet die alte Ansicht vor dem Mounten der nächsten.
Queue, Live-Verbindung, Notifications und Suchshell sind sitzungsweite Dienste;
sie bleiben beim Tabwechsel aktiv, enden jedoch bei Sessionablauf oder `pagehide`.
Ein BFCache-`pageshow` stellt die Dienste einer weiterhin gültigen Sitzung wieder her.

`core/lifecycle.js` bündelt Listener, Timer, Animation-Frames, Observer,
Subscriptions und AbortController. `dispose()` ist idempotent. Requests bekommen
`scope.signal`; zusätzliche Generationen schützen vor verspäteten Antworten von
Transporten, Bild-Decodes und anderen Operationen, die Abbruch nicht garantieren.
Doppelklick-Sperren verhindern doppelte Schreibaufträge. Eine bereits gestartete
Queue-Mutation bleibt sitzungsgebunden, während geschlossene Details keine
verspäteten UI-Änderungen mehr erhalten.

Verbleibende Timer haben konkrete Zwecke:

| Zweck | Eigentümer / Ende |
| --- | --- |
| HTTP-Timeout, WebSocket-Reconnect | zentraler Transport; Requestende bzw. Disconnect |
| Katalog-Retry, Metadaten, Poster-Deadline | Katalog-/Detail-Scope; Tabwechsel oder Detailwechsel |
| Such-Debounce, Formularfeedback | Feature-Scope; neue Eingabe oder Unmount |
| Carousel-Autoplay, Artwork-Übergang | Home-/Artwork-Scope; Verlassen der Ansicht |
| Updater-Status und exakte Neustartprüfung | Updater-Scope; Terminalzustand oder Unmount |
| Startvorhang und Übersetzungs-Debounce | Boot-/Lokalisierungs-Scope; Abschluss oder Sitzungsende |

Polling wird dort beibehalten, wo der vorhandene Serververtrag keinen passenden
Live-Abschluss liefert. Es gibt keine zweite Reconnect- oder Timer-Kette pro Seite.

## Features und DOM-Verantwortung

| Bereich | Module |
| --- | --- |
| Anmeldung, Sitzung, Setup | `auth/`, `setup/`, `settings/account.js` |
| Home | `home/`: Daten/Cache, Hero, Rows/Lanes, Empfehlungen, Layout, Karten, Ranking |
| Filme, Serien, Anime, AniWorld | `discovery/`: Browse, Filter, Metadaten, Zustände und Darstellung |
| Details, Episoden, Filmreihen | `media-details/`, `collections/` |
| Globale und Home-Suche | `search/`; globale progressive Suche ohne künstliche Ergebnisgrenze |
| Queue, Download-Historie, Live-Fortschritt | `downloads/` |
| Abos, Bibliothek und Regeln | `subscriptions/`, einschließlich eigener Serien-Kurzansicht |
| Persönliches Profil, Haushalt, Geschmack | `profile/` |
| Inbox, Kalender, Film-Releases | `notifications/`, `calendar/`, `releases/` |
| Integrationen, Automation, Speicher | `integrations/`, `automation/`, `storage/` |
| Einstellungen und Updater | `settings/` |

Root-Elemente, externe Statusfelder und bereichsübergreifende Aktionen werden in
`composition.js` übergeben. Ein Feature sucht innerhalb seines Roots. DOM-Erzeugung
über `document.createElement`, Fokusverwaltung und bewusst geteilte Shell-Elemente
sind davon zu unterscheiden. Details dürfen ihre explizit übergebenen Modal-Roots
ansprechen, auch wenn diese unter `body` liegen.

## Gemeinsame Darstellung

`shared/components/media-card.js` bildet Medienkarten für Home und Suche ab;
`result-card.js` erhält die bestehende kompakte Katalogdarstellung. Beide nutzen
gemeinsame Artwork-/Statusbausteine. Unterschiedliche vorhandene Layoutvarianten
werden erhalten, keine weiteren vollständigen Kartenrenderer pro Feature ergänzt.
`carousel.js`, `modal.js`, `status-badge.js`, `view-state.js`, `toast.js`,
`infinite-scroll.js` und `startup-curtain.js` besitzen wiederverwendbare Interaktion.
Queue-, Abo- und Notification-Zeilen bleiben in fachlichen Komponenten gebündelt.

Dynamische Ansichten unterscheiden `loading`, `ready`, `empty` und `error`.
Fehler dürfen vorhandene Daten mit Fehlerhinweis erhalten, aber nicht als leere
Ergebnisliste verschleiern. Text wird über `textContent` oder die gemeinsame
Escape-Funktion eingefügt; HTML-Templates bleiben für zusammenhängende feste
Strukturen zulässig.

`api/integration_health.py` liefert den expliziten versionierten Health-Vertrag:
`healthy`, `degraded`, `offline`, `auth_failed`, `disabled`, `unknown`.
Das Frontend visualisiert diesen Vertrag und klassifiziert keine übersetzten
Fehlermeldungen. Nicht genauer bekannte Backend-Ausfälle bleiben `degraded` oder
`unknown`, statt eine konkrete Ursache zu erfinden.

## CSS und Design-Erhalt

`style-tokens.css` definiert Farben, Abstände, Radien und Schatten. Bestehende
Theme-Aliase bleiben erhalten. `styles/components.css` enthält gemeinsame
Grundregeln; Feature-Dateien ergänzen Layout und bereichsspezifische Darstellung.
Zuvor per JavaScript injizierte statische Styles liegen im CSS-Importbaum.
Namen wie `legacy-account.css` bezeichnen weiterhin vorhandene Design-Layer,
keine parallel laufende JavaScript-Implementierung. Die Reihenfolge der Styles
bleibt absichtlich erhalten, damit der Refactor das Design nicht verändert.

Der automatisierte Vergleich prüft 2398 Elemente bei 1440 und 390 Pixeln gegen den
festen Vor-Umbau-Stand `7d93908`. Er ersetzt keine visuelle Neugestaltung und fügt
auch keine solche hinzu.

## Ein neues Feature ergänzen

1. Fachlichen Besitzer und vorhandenen Backend-Vertrag bestimmen.
2. In `features/<bereich>/` eine Factory mit Root, Client und benötigten Callbacks
   anlegen; Server-Snapshots und temporären Entwurf getrennt halten.
3. Nebenwirkungen an `createScope()` binden und beim Unmount beenden.
4. Gemeinsame Karten, Status- und Ladebausteine verwenden; keine eigene HTTP-/WS-Schicht.
5. In `composition.js` verdrahten und in `app.js` mit passender Lebensdauer registrieren.
6. Erfolg, leere Antwort, Fehler, verspätete Antwort und erneutes Mounten testen.

Kein neuer Code unter `window`, keine Inline-Handler und keine Feature-Imports aus
Shell oder Komposition. Die Shell kann Aktionen vermitteln; Fachlogik bleibt beim Feature.

## Update-Kompatibilität und Tests

Die alten Laufzeitskripte unter `web/screens/`, `web/core.js`, `web/store.js`,
`web/loading.js` und die HTTP-Fassade sind entfernt. **`web/i18n.js` muss als
inaktiver Archivmarker erhalten bleiben:** Bereits installierte Updater verlangen
diesen Pfad, bevor sie neuen Code installieren. Die Datei wird nicht geladen.
Der Archiv-Regressionstest hält diesen alten Vertrag bewusst fest.

Beim Updater darf ein früherer Installationsfehler den frisch angebotenen Commit
nicht überschreiben. Die Installation und Neustartprüfung verwenden den exakten
Ziel-SHA; Overnight-Quality-Gates bleiben wirksam.

Prüfungen:

```text
node --test tests/frontend_smoke.test.mjs tests/series_card_summary.test.mjs tests/frontend/subscription_center.test.cjs tests/frontend/core.test.mjs
python -m pytest -q
node tests/frontend/browser-smoke.cjs
node tests/frontend/setup-browser.cjs
node tests/frontend/css-equivalence.cjs
```

Die Browserprüfungen nutzen eine vorhandene Playwright-Installation über
`ROYAL_PLAYWRIGHT` und standardmäßig Edge (`ROYAL_BROWSER` überschreibbar).
HTTP und WebSocket sind deterministische Fixtures. Es werden keine echten
Downloads oder Nutzerdaten verändert. Direkte Testzugriffe auf Shell-Exporte sind
auf den Testkontext beschränkt; die Produktionsseite erzeugt keine solchen Globals.

Python-Gesamttests lokal in einer isolierten Kopie ohne persönliche Konfiguration
starten. Unter Windows sind zwei bestehende Plattformabweichungen bekannt:
POSIX-0600-Dateirechte und `/external`-Pfadnormalisierung. Beide wurden am
unveränderten Overnight-Stand reproduziert. Die vollständige Linux-CI prüft diese
Verträge samt Coverage, Security, Container, E2E und Upgrade/Rollback.
