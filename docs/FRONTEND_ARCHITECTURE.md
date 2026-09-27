# RoyalDownloader Frontend-Architektur

## Aufbau und Einstieg

RoyalDownloader verwendet HTML, CSS und Vanilla JavaScript mit nativen ES Modules.
Es gibt keinen Bundler, keine neue Laufzeitabhängigkeit und keinen Build-Schritt.
`web/index.html` lädt ausschließlich `web/app.js` als Modul. Dieser Einstieg
initialisiert Übersetzung, Anmeldung, Setup und die Anwendung.

`web/js/composition/index.js` führt fachliche Composition-Module zusammen.
Die Module erzeugen ihre Dienste und übergeben benannte Abhängigkeiten und
Callbacks an Feature-Factories. `composition/application.js` verbindet die
Domain-Gruppen mit `web/js/app.js`, das Navigation und Lebensdauer verwaltet.
`createApplication({ core, home, discovery, downloads, profile, subscriptions,
settings, integrations, search })` benennt innerhalb jeder Gruppe die tatsächlich
benötigten Dienste. Es gibt keine globale oder importierbare Service-Registry.

`shell/actions.js` vermittelt globale Navigation, Queue-Dock, Modals und
bereichsübergreifende UI-Aktualisierung. Home-, Discovery-, Profil-, Abo-,
Collection- und Download-Aktionen liegen bei ihren Features und erhalten ihre
Abhängigkeiten als Factory-Parameter. Sie importieren keine Shell-Aktionen.

```text
web/
  index.html, app.js                 DOM-Shell und nativer Einstieg
  i18n.js                           inaktiver Update-Kompatibilitätsmarker
  js/
    composition/index.js            fachliche Komposition zusammenführen
    composition/application.js      gruppierte Application-Lifecycle-Ports
    composition/{domain}.js         Dienste, Roots und Callbacks einer Domäne
    app.js                          Navigation und Sitzungslifecycle
    core/                           API, Store, WebSocket, Lifecycle, Fehler
    shell/                          importierte Shell-Aktionen und Queue-Abbild
    shared/components/              wiederverwendbare UI und Interaktion
    shared/formatters/, utils/       reine Formatierung und Hilfsfunktionen
    shared/constants/               gemeinsame feste UI-Konstanten
    features/                       fachlich abgegrenzte Dienste und Ansichten
  style-tokens.css                   semantische Tokens und Theme-Aliase
  style.css                         geordneter CSS-Importbaum
  styles/                           Komponenten und Feature-Layouts
```

Die ursprüngliche Bestandsaufnahme bleibt unverändert in
[FRONTEND_AUDIT.md](FRONTEND_AUDIT.md) und [frontend-audit.json](frontend-audit.json).
Diese Dateien beschreiben bewusst den Zustand **vor** dem Umbau.

Die nachfolgende Härtung ist vorab in
[FRONTEND_HARDENING_AUDIT.md](FRONTEND_HARDENING_AUDIT.md) mit vollständigem
[Import- und Registry-Inventar](frontend-hardening-audit.json) dokumentiert.
Der [abschließende Importgraph](frontend-hardening-result.json) enthält keine
Zyklen und keine Verletzungen der Schichtgrenzen.

## Komposition und erlaubte Abhängigkeiten

| Composition-Modul | Verantwortung |
| --- | --- |
| `core.js` | Sprache, Shell, Modals, gemeinsame Darstellung und Start |
| `downloads.js` | Queue-Synchronisation und Film-Download-Rückmeldungen |
| `discovery.js` | Film-/Serienzustand, Browse, Details, Anime, AniWorld, Collections |
| `home.js` | Home-Daten, Karten, Empfehlungen, Hero und Layout |
| `profile.js` | Auth, Identität, Haushalt, persönlicher Speicher und Onboarding |
| `subscriptions.js` | Abos, Bibliothek, Regeln und Notifications |
| `integrations.js` | Jellyfin, Health und Medienverfügbarkeit |
| `settings.js` | Setup, Provider, Updater, Speicher, Kalender und Automation |
| `search.js` | globale Suche und Home-Suche |

Die Initialisierung besitzt drei Schritte: `prepare*` erzeugt benötigten Zustand,
`compose*` erstellt die Domain-Dienste, `initialize*` bindet Dienste, deren
konkrete Gegenstellen dann vorliegen. Benannte `getHome`-/`getDiscovery`-Ports
innerhalb der Komposition lösen verzögerte Referenzen auf. Feature-Factories
erhalten daraus einzelne Dienste, Getter oder Callbacks, keinen Domain-Container.
Solche Getter dürfen beim Erzeugen einer Factory nicht vorzeitig aufgerufen
werden. Ein Factory-Ergebnis gehört ausschließlich seiner Domäne; andere
Domänen verändern es nicht. Neue Abhängigkeiten werden am Konstruktor sichtbar.

Automatisch geschützt werden alle Module unter `web/js/`, einschließlich
statischer Imports, Re-Exports und literaler dynamischer Imports:

- `core/` importiert keine höheren Schichten.
- `shared/` importiert keine Features, Shell oder Komposition.
- `features/` importiert weder Shell noch Komposition.
- Shell importiert keine Komposition; der Composition-Root importiert nur seine Module.
- Keine Importzyklen und keine Wiedereinführung von `sharedPresentation`.

Ein Feature innerhalb einer bestehenden Domäne wird dort lokal verdrahtet.
Der zentrale Root ändert sich nur für eine neue Domäne. Neue fachliche Logik
gehört weder in die Komposition noch in die Shell.

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
`composition/<bereich>.js` übergeben. Ein Feature sucht innerhalb seines Roots. DOM-Erzeugung
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
Die Baseline darf bei einem späteren Redesign nur ausdrücklich und mit
dokumentierter Designänderung ersetzt werden, niemals automatisch nach einem Fehler.

## Ein neues Feature ergänzen

1. Fachlichen Besitzer und vorhandenen Backend-Vertrag bestimmen.
2. In `features/<bereich>/` eine Factory mit Root, Client und benötigten Callbacks
   anlegen; Server-Snapshots und temporären Entwurf getrennt halten.
3. Nebenwirkungen an `createScope()` binden und beim Unmount beenden.
4. Gemeinsame Karten, Status- und Ladebausteine verwenden; keine eigene HTTP-/WS-Schicht.
5. Im zuständigen `composition/<bereich>.js` verdrahten; bei einer neuen Ansicht
   die passende Lifecycle-Registrierung in `app.js` ergänzen.
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
In CI installiert der Job `frontend-browser` Playwright 1.62.1 und Chromium
ausschließlich im Runner-Temporärverzeichnis. `ROYAL_BROWSER=chromium` verwendet
den mitgelieferten Browser. Es entsteht keine Build-Pipeline oder App-Abhängigkeit.
Alle drei Browserprüfungen laufen bei jedem PR sowie Push nach `overnight`/`main`
und bei manuellen oder wiederverwendeten Quality-Läufen. `verify` hängt davon ab
und schlägt ausdrücklich fehl, wenn das Browser-Gate nicht erfolgreich war.
HTTP und WebSocket sind deterministische Fixtures. Es werden keine echten
Downloads oder Nutzerdaten verändert. Direkte Testzugriffe auf Shell-Exporte sind
auf den Testkontext beschränkt; die Produktionsseite erzeugt keine solchen Globals.
Der Browser-Test importiert den exakt gleichen Einstieg einschließlich Query-String
wie das HTML, damit keine zweite Application-Instanz entsteht.

Python-Gesamttests lokal in einer isolierten Kopie ohne persönliche Konfiguration
starten. Unter Windows sind zwei bestehende Plattformabweichungen bekannt:
POSIX-0600-Dateirechte und `/external`-Pfadnormalisierung. Beide wurden am
unveränderten Overnight-Stand reproduziert. Die vollständige Linux-CI prüft diese
Verträge samt Coverage, Security, Container, E2E und Upgrade/Rollback.

## Carousel- und Rendering-Verträge

`shared/components/carousel-geometry.js` berechnet viewportabhängige Randpuffer
und äquivalente Schleifenpositionen. `features/home/rail-renderer.js` besitzt die
Card-Identitäten, Artwork-Vorbereitung und die scoped Resize-/Visibility-Observer.
Alle Originale bleiben zugänglich; nur Randkopien sind `aria-hidden`/ohne Tabstopp.
Neue Rails verwenden denselben Renderer statt eigene Scroll-Listener oder Vollkopien.

`shared/components/carousel.js` lässt native Touch-/Pen-Gesten und Momentum laufen.
Loop-Korrektur erst bei `scrollend` oder nach 180 ms Ruhe und beendetem Kontakt.
`pointercancel` eines Touch-Pointers bedeutet natives Panning, nicht Finger-abheben.
Endlose Rails verzichten auf erneutes CSS-Snapping am Wrap; endliche Rails behalten
das bestehende Proximity-Snap. Resize erhält eine logische Position, keine alte Pixelzahl.

Weit entfernte Rail-Abschnitte nutzen `content-visibility:auto` mit gemessener
Intrinsic-Höhe. In/nahe dem Viewport bleibt die bisherige Paint-Darstellung erhalten.
Der Scroll-Container selbst wird nicht skipped: Das würde Browser-Scrollpositionen
und Schatten beeinträchtigen. ResizeObserver-Schreibzugriffe erfolgen im nächsten
Frame statt während der Observer-Auslieferung (insbesondere für WebKit).

Zusätzliche lokale Tests:

```text
node tests/frontend/mobile-browser.cjs
node tests/frontend/webkit-mobile.cjs
node tests/frontend/offscreen-browser.cjs
node tests/frontend/performance-benchmark.cjs
node tests/frontend/performance-budget.cjs baseline/metrics.json current/metrics.json
node tests/frontend/carousel-visual.cjs
```

Für den gefüllten Bildvergleich `ROYAL_VISUAL_BASELINE_WEB` auf `web/` eines
unveränderten Worktrees von `d3aada9` setzen. Testwerkzeuge bleiben isoliert:
Playwright 1.62.1, PNGJS 7.0.0 und Pixelmatch 7.2.0. Keine App-/Build-Abhängigkeiten.
`ROYAL_SCROLLEND_FALLBACK=1` prüft den Touch-Fallback ohne scrollend-Auslieferung.

`verify` benötigt Chromium-Browser, WebKit-Mobile und Performance-Gate. Das
Performance-Gate misst eingefrorene Baseline und aktuellen Stand auf demselben
Worker, drei Samples pro CPU-Profil. Mindestens 40 % weniger volle Cards bei
weiterhin 97 tatsächlich gerenderten logischen Fixture-Titeln sind verpflichtend.
Medianschranken für Render-/Layout-/Style-/Script-Zeit und TBT besitzen Spielraum
für gemeinsam genutzte Runner. Rohwerte und Bilddifferenzen werden archiviert.

Chromium injiziert echte kontinuierliche Touch-Gesten. WebKit prüft echte Touch-
Taps, Layout und Resize/Scroll-Verträge; seine öffentliche Playwright-API kann
keine kontinuierlichen nativen Swipes einspeisen. Ein physischer Safari-Test wird
damit nicht behauptet. WebKit läuft auf PRs sowie über Quality vor Releases;
der zusätzliche geplante Overnight-Lauf wird von GitHub erst aktiviert, sobald
die Workflowdatei auch auf dem Default-Branch vorhanden ist.

Messungen und bewusst unveränderte Effekte/Fonts:
[Baseline](FRONTEND_PERFORMANCE_BASELINE.md), [Ergebnis](FRONTEND_PERFORMANCE_RESULT.md).
