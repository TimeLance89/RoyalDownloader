# RoyalDownloader Frontend-Architektur

## Status und Geltungsbereich

Royal bleibt HTML, CSS und Vanilla JavaScript. Native ES Modules werden direkt vom
bestehenden StaticFiles-Server ausgeliefert. Es gibt keinen Bundler, keine neue
Laufzeitabhängigkeit und keinen zusätzlichen Build-Schritt.

**Die Gesamtmigration ist noch nicht abgeschlossen.** Dieser Stand migriert den
HTTP-Transport, die WebSocket-Verbindung, Releases einschließlich Konfiguration,
Queue-Darstellung und Queue-Ereignisse, Profil und Haushaltsauswahl, Modulverwaltung, Automation, Serien-/Film-Abo-Datendienste, Listenansichten und Regeldialoge, Benachrichtigungen, Speicherverwaltung und Verschiebejobs,
Serienkalender, Modal-Steuerung sowie Home-Katalogdaten, Cache, Hintergrundreservoir,
Katalog-Artwork, Hero, Rows, Empfehlungen und Carousel der Startseite. Auch globale Suche,
Anmeldung, Ersteinrichtung, allgemeine Einstellungen, Provider-Auswahl, Kontoverwaltung,
Updater, Jellyfin/Seerr/TMDB/Telegram-Konfiguration und Ordnerwahl sind native Features.
Auch Discovery, Film-/Seriendetails, Anime, AniWorld und Filmreihen liegen in nativen
Feature-Modulen. Klassische Shell-Skripte und dünne Funktionsbrücken bleiben bis zur
abschließenden Umstellung bestehen. Sie sind keine Vorlage für neuen Code.

Die Bestandsaufnahme steht in [FRONTEND_AUDIT.md](FRONTEND_AUDIT.md). Das zugehörige
[Vollinventar](frontend-audit.json) beschreibt den Stand **vor** der Migration,
einschließlich aller Dateien unter `web/`, Router, DOM-Ziele und Timer.

## Ordner und Verantwortlichkeiten

```text
web/
  index.html                      bestehende Shell und DOM-Verträge
  app.js                          nativer Einstieg und Startsequenz
  core.js, store.js, screens/      noch nicht vollständig migrierte Laufzeit
  js/
    app.js                        Feature-Registrierung und Anwendungslifecycle
    legacy-adapter.js              einzige Kompositionsstelle zu klassischen Presentern
    core/
      api.js                      einziger HTTP-Transport
      errors.js                   ApiError, Abbrucherkennung, Subscriber-Fehler
      store.js                    gemeinsamer Client-Zustand
      websocket.js                einzige Socket-Instanz und Reconnect
      lifecycle.js                Abort, Listener, Timer, Frames, Observer
      navigation.js               mount/unmount und explizites refresh
    shared/components/
      media-card.js               Karten-Markup für Home/Suche und ihre Verwender
      status-badge.js             Jellyfin-Medienstatus und zugängliche Beschriftung
      carousel.js                 Schleife, Scrollziele, Fokus und Steuerelemente
      modal.js                    Medien-Overlay und Fokussteuerung
      dialog.js                   allgemeiner Dialog-Scope, Tastatur und Fokusrückgabe
      view-state.js               sichere Loading-/Empty-/Error-Darstellung
      infinite-scroll.js          aktiver Katalog, Desktop-/Dokument-Scroll und Frame-Abbruch
    features/
      downloads/                  Live-Abos, Queue-Events und Queue-View
      discovery/movie-hero.js     Film-Billboard mit lokalem Zustand und Rotation
      home/                       Katalogdaten/Cache/Reservoir, Lifecycle, Hero und Datenreihen
      releases/                   lokale View, API-Zugriff und Einstellungen
      calendar/                   Sendeplan-Snapshot, validierter Cache, Filter und View
      profile/                    Profil-View, persönliche Requests, Haushalt, Kontomenü
      auth/                       Server-Anmeldestatus und getrennt gebundene Login-Formulare
      setup/                      Ersteinrichtung, Schritttexte und lokaler Formularzustand
      search/                     explizite Suche, progressive Ergebnisse, Filter und Abbruch
      settings/                   Navigation, Speichern, Provider, Benutzer, Updater und Ordnerwahl
      integrations/               Health-Vertrag und Konfigurationsformulare
      storage/                    Layout, Views, Aktionen, Scoped API und Verschiebejobs
      automation/                 Layout, Formzustand, Policy-View und Lifecycle
      notifications/              Inbox-Modell, View, API und Shell-/Aktionslifecycle
      subscriptions/              gemeinsamer Server-Snapshot, Listenmodell, View und Lifecycle
      system/server-build.js      öffentlicher Build-Heartbeat für Updates
  style-tokens.css                 zentrale Tokens, bisherige Namen als Aliase
  style.css                       geordnete CSS-Imports
  styles/components.css           gemeinsame Statusdarstellung
  styles/                         bestehende Layout-/Feature-CSS
```

`legacy-adapter.js` injiziert existierende Funktionen und Zustandsreferenzen in
die neuen Module. Dynamische Callbacks erhalten die noch bestehenden Discovery-
Dekoratoren. `sharedPresentation` und `queueView` sind gezielte Übergangsbindungen
im klassischen Scope, keine neue öffentliche `window`-API. Beim Migrieren eines
Aufrufers wird sein Adapter entfernt. Neue Features importieren keine klassischen
Globals und schreiben keine Eigenschaften auf `window`.

Ersetzte Implementierungen wurden entfernt: eigener Release-Transport, altes
Release-Skript, WebSocket-Erstellung/Reconnect aus `core.js`, Queue-Rendering dort,
Hero-/Karten-/Carousel-Implementierung in ihren bisherigen Dateien und die
timerbasierte Loader-Kette in `api.js`, die Modal-Implementierung in `core.js`,
das klassische `module-manager.js` und die bisherigen Profil-/Haushaltspresenter. Kleine Weiterleitungen bleiben nur für
noch vorhandene klassische Aufrufer bestehen.

## Application State, Server State und Feature State

`appStore` hält aktuell `user`, `language`, `navigation` und `connection`.
`set(patch)` meldet ausschließlich Änderungen; `subscribe(callback)` liefert eine
Abmeldefunktion. Der Store ist flach und speichert keine Queue, Medienkataloge,
Formulare oder Konfiguration. Die Socket-Instanz ist ein Modul-Singleton und wird
nicht in serialisierbaren Zustand gelegt.

Serverdaten bleiben Serverdaten: Queue, Jobhistorie, Bibliothek, Abonnements,
Integrationen, Profile und Einstellungen werden über bestehende Verträge geladen.
Lokale Kopien dienen ausschließlich der Darstellung. Es gibt keinen neuen
persistenten Frontend-Cache für persönliche Daten.

Release-Filter, Suchtext, geladene Termine und Meldungen leben in der Closure der
Feature-Instanz. Aufeinanderfolgende Mounts behalten Filter, lösen aber frische
Requests aus. Ein verlassenes Mount darf keine Ergebnisse in ein neues Mount
schreiben: asynchrone Abläufe halten ihren ursprünglichen Scope fest und prüfen
`current.active` nach jedem relevanten `await`.

Der bisherige `state` aus `web/store.js` mischt weiterhin viele Serverkopien und
UI-Felder. Die Queue erhält daraus Referenzen am Adapter. Die sechs Home-Kataloge
sowie ihre Ladezustände gehören dagegen ausschließlich `features/home/data.js`;
klassische Presenter lesen dessen Snapshot. Home-Filter und Layout bleiben vorerst
im klassischen UI-State. Die vollständige Zerlegung des Legacy-State ist noch offen.

## Persönliche Requests sind keine Queue-Historie

Der bestehende `core/personal_requests.py` persistiert benutzereigene Anfragen
unabhängig von Queue-Bereinigung und Retry. `/api/me/profile-summary` liefert
`recent_downloads` aus `PersonalRequestStore.recent_for_user`, nicht aus der Queue.
Dieser Backendvertrag wurde unverändert übernommen. `request.id`, `job_id` und
`media_key` haben unterschiedliche Bedeutungen. Jobversuche bleiben Teil der
Backend-Downloadlogik. Niemals die persönliche Historie aus `/api/queue` bauen.

## API Layer

```js
import { api } from "../../core/api.js";

const data = await api.get("/api/releases", { signal: scope.signal });
await api.post("/api/releases/check", { id }, { signal: scope.signal });
await api.put(path, body, { signal: scope.signal });
await api.patch(path, body, { signal: scope.signal });
await api.delete(path, { signal: scope.signal });
```

Nur `core/api.js` ruft `fetch` auf. Es setzt Same-Origin-Credentials, JSON-Header,
serialisiert Bodies, behandelt leere Antworten und meldet ungültiges JSON.
`ApiError` enthält `status`, `code`, `resource` und optional `cause`.
Netzwerkfehler tragen `network_error`, Deadlines `request_timeout`; bewusste
Abbrüche bleiben `AbortError`. Nicht aus einem Fehler eine leere Ergebnisliste
machen. Die vorhandene Cookie-/Origin-Sicherheit bleibt bestehen; es wird kein
erfundener CSRF-Header eingeführt.

Standarddeadline: 30 Sekunden. Releases, Kalender und gezielte Jellyfin-Abfragen
nutzen 15 Sekunden. Die bestehende Provider-Vollsuche behält mit `timeoutMs: 0`
ihre unbegrenzte Laufzeit. Jeder Timeout beendet tatsächlich den Transport.
`timeoutMessage`, `headers`, `cache` und `signal` sind Request-Optionen.

Gleichzeitige GETs mit denselben Optionen und demselben Scope-Signal werden
zusammengeführt. Verschiedene Signals teilen keinen Abbruch. Nach Abschluss wird
der Eintrag entfernt; Mutationen und Antworten werden nicht dauerhaft gecacht.
So können Nutzerwechsel keine gespeicherten Antworten eines anderen Nutzers
übernehmen. Die alten benannten API-Methoden delegieren in dieselbe Instanz.

401 ruft den zentralen Session-Handler auf, außer bei `/api/auth/*`, damit ein
falsches Passwort das Loginformular nicht neu aufbaut. Sessionablauf beendet die
migrierten Views und Live-Abos. Erfolgreiche erneute Anmeldung lädt die Anwendung
wie bisher neu.

## WebSocket Lifecycle

Es gibt genau einen `websocket`-Singleton. `connect()` ist idempotent;
`disconnect()` schließt die Verbindung, verwirft ihre Generation und entfernt
Reconnect-Timer. Wiederverbindung beginnt bei ungefähr zwei Sekunden und steigt
mit Jitter bis ungefähr 30 Sekunden. Der Status steht im `appStore`.

```js
import { websocket } from "../../core/websocket.js";
scope.add(websocket.subscribe("queue_update", message => render(message.queue)));
```

Die echten Backend-Namen bleiben erhalten: `progress`, `job_done`, `queue_started`,
`queue_update`, `queue_done`, `provider_status`, `watchlist_update`,
`movie_subscriptions_update`, `jellyfin_update`, `updater_install`, `updater_config`
und `log`. Keine erfundenen Topics im Frontend verwenden.

`connection.open` stellt `isCurrent()` für nachgeladene Snapshots bereit. Eine
veraltete Verbindung darf weder Nachrichten noch ihre späteren HTTP-Snapshots
anwenden. Nach Reconnect werden Queue/History, Abos und Jellyfin-Ansichten wie
bisher synchronisiert. Fehler einzelner Subscriber blockieren andere nicht.
Close-Code 1008 beendet Retries und fordert die Anmeldung an.

`/ws` authentifiziert mit dem bestehenden Cookie. Der Server hat kein
Application-Ping/Pong-Protokoll; deshalb gibt es keinen erfundenen Pong-Timeout.
WebSocket-Protokoll-Heartbeat bleibt serverseitig. Der separate HTTP-Build-
Heartbeat erkennt Updates/Serverrestart und lädt bei geänderter Build-ID neu.

## Feature Lifecycle und Navigation

`createNavigation().register(name, feature, root)` erwartet `mount(root, options)`,
`refresh()` und `unmount()`. `activate` unmountet zuerst den bisherigen Besitzer;
erneutes Aktivieren derselben Ansicht erzeugt keine zusätzlichen Listener oder
Requests. Explizites Neuladen verwendet `refresh()`.

```js
import { createScope } from "../../core/lifecycle.js";
import { api } from "../../core/api.js";

export function createFeature() {
  let scope;
  return {
    mount(root) {
      if (scope) return;
      const current = scope = createScope();
      current.listen(root, "click", handleClick);
      // Ladefunktion behandelt loading/ready/empty/error und prüft current.active.
      void load(root, current);
    },
    refresh() { /* dieselbe Ladefunktion, keine erneute Listenerregistrierung */ },
    unmount() { scope?.dispose(); scope = null; },
  };
}
```

`scope.listen`, `timeout`, `interval`, `frame`, `observe` und `add(unsubscribe)`
besitzen die jeweiligen Ressourcen. `scope.signal` gehört zu API-Aufrufen dieses
Mounts. `dispose()` bricht ab und räumt rückwärts und idempotent auf. Auch nach
einem fehlerhaften Cleanup werden die übrigen Ressourcen freigegeben.

Das bestehende `switchTab` meldet derzeit `royal:navigate` an die neue Navigation.
Diese Brücke wird entfernt, wenn alle klassischen Tab-Aufrufer migriert sind.
Die Queue ist eine globale Sidebar: ihr Scope lebt während der Sitzung, nicht nur
während eines einzelnen Tabs. Releases pollen höchstens drei Minuten, nur bei
laufendem Backend-Abgleich und nur im aktiven Scope. Dafür gibt es bisher kein
WebSocket-Ereignis. Home-Tageswechsel, Hero und Carousel gehören zum Home-Scope.

## Komponenten und CSS

Die Media Card bekommt Medienwerte, Darstellung und Callbacks; sie kennt weder
Queue-APIs noch Benutzerprofile. Titel werden mit `textContent` eingefügt.
Artwork-Fallback, Lazy Loading, Card-Dekoratoren, Rangfolge und zugängliche
Bedienelemente bleiben erhalten. Carousel-Schleifenkopien bleiben aus der
Tastaturreihenfolge ausgeschlossen. Row-Rendering erhält DOM-Knoten, wenn ihre
Signatur unverändert ist, statt Poster und Fokus unnötig neu aufzubauen.

`view-state.js` erzeugt Loading-/Empty-/Error-Knoten mit passenden ARIA-Rollen.
Die Releases behalten ihre bisherigen vier Zustände und die gesonderte Anzeige
für fehlende Konfiguration. Queue-Fehler bleiben sichtbar und können erneut
geladen werden; vorhandene Queue-Daten bleiben bei einem Aktionsfehler sichtbar.

Die semantischen Tokens `--color-*`, `--radius-*`, `--spacing-*` und `--shadow-*`
stehen in `style-tokens.css`. Alte Namen wie `--bg` oder `--accent` sind Aliase mit
identischen Werten. Reihenfolge und Sonderdarstellungen der vorhandenen Styles
bleiben bestehen. Noch nicht alle Farbduplikate wurden ersetzt. Neue gemeinsame
Komponenten verwenden Tokens, Feature-CSS enthält die spezielle Anordnung.

## Neue Features ergänzen

1. Vorhandenen Backendrouter und dessen Antwort-/Fehlervertrag prüfen.
2. `web/js/features/<name>/` mit API-Funktionen, lokaler Zustandsverwaltung und
   View/Lifecycle anlegen. Kleine Features benötigen keine künstliche Dateiflut.
3. API-Funktionen importieren ausschließlich `core/api.js`; keine eigene
   Authentifizierung, Timeoutimplementierung oder `fetch`-Stelle hinzufügen.
4. Gemeinsame Darstellung aus `shared/components` konfigurieren. Nur den
   übergebenen Root und bewusst injizierte Shell-Aktionen verwenden.
5. In `js/app.js` registrieren. Live-Abos mit `scope.add` besitzen lassen.
6. Leere Daten, HTTP-/Health-Fehler, Abbruch, schnelle Rücknavigation und doppelte
   Aktivierung testen. Serverseitig bestätigte Persistenz als Wahrheit behandeln.

## Noch erforderliche Migrationsschritte

Die ursprünglichen Abschlusskriterien sind ausdrücklich noch nicht vollständig
erfüllt. Offen bleiben insbesondere:

- Discovery, Suche, Details, die verbleibenden Abo-Seitenleisten/Archive und
  übrige Einstellungen vollständig in native Feature-Module überführen.
- Den Legacy-State und die zahlreichen globalen Funktionsdekoratoren auflösen;
  die übrigen lokalen Timer/Observer aus dem Vollinventar mit Besitzern versehen.
- Home-Empfehlungslogik und den verbleibenden Artwork-/Dock-Lifecycle vollständig
  migrieren. Datenquellen, Cache, Reservoir und Metadaten-Anreicherung sind bereits
  native Module; sämtliche bisherigen Katalogquellen bleiben erhalten.
- Weitere Kartenvarianten, spezielle Dialoge, Toasts, Skeletons und Formularkomponenten
  konsolidieren. Die neuen Module ersetzen noch nicht jede Kartenvariante.
- Ein gemeinsames Integration-Health-Modell mit realen Backendverträgen einführen.
  Medienverfügbarkeit in Jellyfin darf dabei nicht mit Integration-Health
  verwechselt oder aus Fehlermeldungstexten erraten werden.
- Verbliebene CSS-Duplikate nach visueller Gegenprüfung entfernen und sämtliche
  realen Provider-/Integrationsabläufe in einer eingerichteten Testinstanz prüfen.

## Prüfung dieses Standes

```sh
node --test tests/frontend_smoke.test.mjs tests/series_card_summary.test.mjs tests/frontend/subscription_center.test.cjs tests/frontend/core.test.mjs
python -m pytest -q
```

Die Core-Tests laufen auch in der bestehenden CI. Der zusätzliche Browser-Smoke
`node tests/frontend/browser-smoke.cjs` verwendet ein vorhandenes Playwright
(`ROYAL_PLAYWRIGHT` kann auf dessen Paket zeigen, `ROYAL_BROWSER` wählt den Kanal).
Dies ist ein optionales Testwerkzeug, keine Frontend-Laufzeitabhängigkeit.

Browser-Smoke mit deterministischen API-/WS-Fixtures: Start, Releases-Filter,
Loading/Empty/Error, schnelle Navigation, Abbruch später Antworten, Settings,
Queue-Fortschritt/Abbruch/Abschluss, Server-Reconnect mit genau einem Snapshot,
100 Medien/300 Carousel-Karten, mobile Darstellung, Sessionablauf und erneutes
Login einschließlich Reload. Zusätzlich: Modal-Fokus/Tab/Escape, abgebrochene
Modal-Frames, dreifache Modulverwaltung mit genau einer Schreiboperation je Aktion,
persistente persönliche Anfragen bei leerer Queue, Profil-Fehler/Retry, Wiederbesuche
und verspätete Antworten nach geschlossener Haushaltsauswahl. Er prüft auch Modul-404
und JavaScript-Fehler.

`node tests/frontend/css-equivalence.cjs` vergleicht die berechneten Styles der
statischen Shell mit den Styles aus Git HEAD. Vor dem Commit geprüft: je 2.266
Elemente bei 1440 und 390 Pixel Breite identisch. Der zweite überschreibende
`:root`-Block wurde in die zentrale Tokendatei integriert; 338 identische Farbwerte
verwenden jetzt dieselben Tokens. Farbtöne wurden dabei nicht angenähert.
Diese Tests ersetzen keine echten Providerdownloads oder Jellyfin-/Storage-
Integrationstests.

Die Python-Gesamtsuite wurde außerdem in einem isolierten Checkout ohne lokale
Benutzerkonfiguration geprüft. Die bekannten Windows-Abweichungen betreffen
POSIX-Dateirechte des Setup-Tokens und Slash-Normalisierung eines Storage-Pfads;
beide scheitern auch ohne diesen Frontend-Refactor. Keine Backendlogik wurde dafür
verändert.

Ergebnis am 26.09.2026: 105 JavaScript-Tests bestanden; Browser-Smoke bestanden,
keine JavaScript-Fehler oder Modul-404; Python 819 bestanden, 10 übersprungen,
2 bereits vorhandene Windows-Abweichungen. Zusätzlich wurden alle 99 JavaScript-Dateien mit `node --check` geprüft. Die Browsertests verwenden Fixtures und
bestätigen daher keine echten Provider- oder Integrationszugänge.


## Profil, Haushalt und Modulverwaltung

Das Profil besitzt seine DOM-Root, den aktuellen Request und die Listener der
sichtbaren Ansicht. Navigation beendet diese Ressourcen. Die persönliche Historie
kommt unverändert aus `/api/me/profile-summary` und dem backendpersistenten
User-Request-Speicher. Die Queue wird hierfür nicht gelesen. Gleichzeitige Refreshs
teilen nur den laufenden Request; ein neuer Besuch liest einen neuen Snapshot.

`profile/menu.js` gehört zur angemeldeten Shell und liest die Identität aus
`appStore`. `profile/household.js` besitzt einen separaten Scope für jede geöffnete
Auswahl. Schließen verwirft Requests, Button-Listener und den verzögerten Fokus.
Die verbleibende klassische Profildatei enthält nur Übergangsaufrufe und die
Benutzergrenze für noch nicht migrierte Browser-Caches.

`settings/modules.js` mountet zusammen mit den Einstellungen. Schreiboperationen
bleiben unmittelbar serverpersistent; ihre Events verändern den Dirty-State des
allgemeinen Formulars nicht. Requests und gerenderte Listener werden beim Verlassen
entfernt. Health und Runtime-Status stammen unverändert aus `/api/modules`.


Der Film-Hero in `discovery/movie-hero.js` besitzt Kandidaten, Auswahlindex und
Pausenzustand lokal. Seine Katalogquelle wird injiziert, nicht kopiert. Die bisherige
Auswahl-/Bewertungslogik ist erhalten. Navigation beendet Rotation, Übergangsframes
und Listener; der Browser-Test prüft wiederholtes Mounten und genau einen Effekt
je Klick. `state.fp` enthält diese reinen Präsentationsfelder nicht mehr.


## Speicherverwaltung

`storage/index.js` besitzt die Aktionen und den Lifecycle des sichtbaren
Speicherabschnitts. `layout.js` installiert das bestehende Markup, `view.js` rendert
Server-Snapshots. `api.js` bindet sämtliche Requests an den aktuellen View-Scope;
der HTTP-Transport bleibt ausschließlich in `core/api.js`. Die bisherige globale
Überschreibung von `api.post` ist entfernt. Ein gestarteter Transfer wird direkt an
`jobs.accept(job)` übergeben, ohne eine zweite globale Ereignisschicht.

Storage-Endpunkte senden derzeit keine WebSocket-Ereignisse. Daher bleiben die
beiden fachlich erforderlichen Polls (Belegung 5 Sekunden, Jobs 2,5 Sekunden)
erhalten, laufen aber nur im geöffneten Speicherabschnitt. Ausblenden des
Abschnitts, Navigation und Sessionende beenden Requests, Listener, Timer und
Observer. Parallele Polls werden zusammengefasst; Antworten vor einer neueren
Job-Übernahme dürfen diesen Job nicht überschreiben. Backendjobs laufen unabhängig
von der Ansicht weiter und werden beim Wiederöffnen neu abgefragt.

Die alten `storage-manager.js` und `storage-move-jobs.js` sind entfernt. Die
zugehörigen Styles liegen im CSS-Manifest statt in dynamischen Style-Elementen.
Browser-Fixtures prüfen dreifaches Speichern, Planen/Starten eines Transfers,
Konfliktsperren, Abschluss, HTTP-Fehler, späte Antworten und ausbleibende Polls nach
Navigation. Diese Prüfung führt keine realen Dateioperationen aus.


## Automation

`automation/index.js` verwendet direkt den bestehenden `/api/automation/policy`-
Vertrag. Die klassischen API-Methoden und `applyAutomationCfg` werden nicht mehr
überschrieben; ihr ersetzter Code und der suchabhängige Scriptloader sind entfernt.
`layout.js` enthält das bestehende Markup, `view.js` die Eingabekodierung und die
Darstellung der vom Backend berechneten Policy-Zustände. Scheduling-Entscheidungen
bleiben im Backend.

Die einmalige Einstellungen-Initialisierung hat einen eigenen kurzlebigen Request-
Scope. Der sichtbare Automation-Abschnitt besitzt den 15-Sekunden-Poll für Laufzeit-
und Streamingstatus, für den kein WebSocket-Topic existiert. Ausblenden, Navigation,
Sessionende und Pagehide beenden die jeweiligen Ressourcen. Pending-Reads sind
zusammengefasst. Eingaben während eines Requests werden über eine Änderungsversion
und einen lokalen Entwurf vor späten Antworten geschützt. Speichern verwendet den
vollständigen vorhandenen Policy-Vertrag; ohne erfolgreich geladenen Grundzustand
werden keine geratenen Regeln gespeichert.

Browser-Fixtures prüfen Nachtfenster, übernommenes Wochenendfenster, Slot- und
Bandbreitenwerte, genau eine Policy-Schreiboperation und erhaltene Eingaben bei
verspäteten Antworten. Polls überschreiben keine ungespeicherten Einstellungen.


## Benachrichtigungen

`notifications/model.js` projiziert die vorhandenen Abo-Zustände in die Inbox-
Filter. Offene, eingeplante, geladene und fehlerhafte Folgen bleiben unabhängige
Mengen. `view.js` rendert ausschließlich innerhalb der übergebenen Glocken-Root;
Filter, Quittierung und Rückmeldungen liegen lokal im Controller, nicht in `state.wl`.
Inbox, Liste und Detailansichten lesen den gemeinsamen Server-Snapshot aus
`subscriptions/state.js`. Dieser Dienst besitzt die Request-Deduplizierung,
den Prüfmutex und die Abbruchlogik; die Inbox hält keine Kopie der Abonnements.

Die Glocke gehört zur angemeldeten Shell. Jede geöffnete Inbox hat einen eigenen
Aktions-Scope. Schließen, Navigation, Sessionende und Pagehide brechen laufende
Aktionen ab und entfernen die Zeilenlistener. Geschlossene Inboxen aktualisieren
nur ihre Zusammenfassung. Es entstehen keine zusätzlichen WebSocket-Verbindungen
oder Polls. Nach explizitem Quittieren wird ein frischer Abo-Snapshot geladen;
der möglicherweise alte Inhalt der Quittierungsantwort wird nicht übernommen.
Eine inzwischen eingegangene Live-Aktualisierung hat Vorrang vor dem GET-Ergebnis.

Die Tests importieren das native Inbox-Modell und den Controller direkt. Neben den
bisherigen Filter-, Zähler-, Fehler- und Quittierungstests prüfen sie Abbruch beim
Schließen, wiederholtes Mounten ohne doppelte Listener und Vorrang neuer Live-Daten.
Der Browser-Test prüft wiederholtes Öffnen, Filter, explizites Quittieren mit dem
Zeitstempel der ungelesenen Folge und eine einzelne Abo-Prüfung.


## Serien-Abonnements und Listenansicht

`subscriptions/state.js` gehört zur angemeldeten Anwendung. Es besitzt den
Server-Snapshot, Transportfehler und den gemeinsamen Prüfstatus. Nur dieser Dienst
abonniert die Abo-Daten aus `watchlist_update` und `jellyfin_update`; nach
`connection.open` lädt er genau einen neuen Snapshot. Reconnect ersetzt ältere
Reads. Neuere Live-Daten haben Vorrang vor verspäteten HTTP-Antworten. Ein laufender
Read und eine laufende Prüfung werden unter den Verbrauchern geteilt. Sessionende
und Pagehide lösen Abonnements und brechen sämtliche eigenen Requests ab.

`subscriptions/index.js` besitzt Filter, Sortierung, Darstellung, Auswahl und
Rückmeldungen der bestehenden Bibliothek. Die Navigation mountet das Feature auf
`#tab-bibliothek`. Zeilenlistener werden vor jedem Render entfernt; Navigation
entfernt zusätzlich die Bedienlistener und bricht Prüf-/Entfernungsaktionen ab.
Späte Antworten können eine verlassene Ansicht nicht verändern. Serverfehler,
initiales Laden, leere Liste und leeres Filterergebnis bleiben unterscheidbar.

Noch klassische Serienansichten, Kalender und Account lesen den Dienst über
`sharedPresentation.subscriptions.get()`; sie besitzen keinen zweiten Server-
Snapshot. `state.wl` wurde vollständig entfernt. Der Adapter aktualisiert
Detailflags und Seitenleiste nur bei einem neuen Server-Snapshot. Die frühere globale Listenansicht und ihre
Ereignisregistrierungen wurden entfernt. Die Browser-Prüfung deckt wiederholtes
Mounten, Suche, Auswahl, Darstellung, genau eine Prüfung je Aktion, Abbruch beim
Verlassen und Entfernen ausgewählter Abos ab.


`subscriptions/rules.js` besitzt den Abo-Regeldialog einschließlich lokalem
Entwurf, vorhandener Jellyfin-Voraussetzungsanzeige und den unveränderten Add-,
Mode- und Remove-Verträgen. Die gemeinsame Komponente `dialog.js` verwaltet
Fokus, Escape, Backdrop, Tab-Begrenzung und einen Scope je Öffnung. Schließen,
Navigation und Sessionende entfernen die Listener und brechen laufende Requests
ab. Speichern/Entfernen teilen einen lokalen Schreibschutz; alte Antworten dürfen
weder einen neu geöffneten Dialog schließen noch dessen Eingaben ändern.
Der bisherige Fokus-Timer, globale Dialogvariablen und ersetzte API-Fassaden wurden
entfernt. Browser-Fixtures prüfen wiederholtes Speichern, Add-Payload mit stabiler
Medienidentität, Fokusbegrenzung sowie Schließen während einer verzögerten Antwort.

Das obsolete `screens/notifications.js` und seine Shell-Einbindung sind entfernt.
Der verbleibende klassische Einstieg in die Serien-Detailansicht liegt vorerst in
`screens/library.js`; er migriert zusammen mit der Detailansicht. Die Inbox greift
bereits ausschließlich über den injizierten Öffnen-Callback darauf zu.


Der bestehende `/api/watchlist/remove`-Handler sendet nach erfolgreichem Persistieren
zusätzlich `watchlist_update` mit seinem Antwort-Snapshot. Zuvor sendete er nur
`queue_update`; nach einem clientseitigen Request-Abbruch konnte die Abo-Liste
deshalb veraltet bleiben. Die fachliche Lösch-/Queue-Logik bleibt unverändert.
Ein Backendtest prüft den persistierten Snapshot und ausbleibende Ereignisse bei
Persistenzfehlern. Der Browser-Test schließt die Ansicht während einer Löschung
und prüft, dass das Live-Ereignis den gemeinsamen Serverzustand trotzdem aktualisiert.

Gezielter Ruff-Check der berührten Python-Dateien: Der neue Persistenztest ist
sauber. `api/api_library_router.py:6` meldet weiterhin `I001` für die bestehende
Importsortierung; derselbe Befund wurde mit dem unveränderten Git-HEAD bestätigt.


## Film-Abonnements

`subscriptions/state.js` erstellt je eine getrennte Instanz für Serien und Filme.
Beide nutzen denselben Request-/Scope-Mechanismus, aber eigene Snapshots und
Topic-Abonnements. Die Filminstanz verwendet ausschließlich `/api/movie-subscriptions`,
`keys` im Check-Payload und `movie_subscriptions_update`. Das frühere globale
`state.movieSubscriptions` und dessen zentraler WS-Handler sind entfernt.

`movie-model.js` enthält die bestehende Identitäts- und Statusprojektion:
TMDB-Identität hat Vorrang vor Provider-Slugs. `movies.js` mountet die Film-Abo-
Sektion gemeinsam mit der Filmansicht; `movie-view.js` besitzt ihre Zeilenlistener.
Laden, leerer Bestand, vorhandene Daten und Transport-/Prüffehler werden getrennt
dargestellt. Ausblenden entfernt Listener und bricht laufende Prüfungen ab.

`movie-rules.js` nutzt den gemeinsamen Dialog-Scope. Qualitätsziel, Löschregel und
Upgrade-Präferenz liegen im lokalen Entwurf. Schreiben ist während eines laufenden
Requests gesperrt. Escape, Navigation, Sessionende und Pagehide brechen die eigenen
Anfragen ab; alte Antworten dürfen keinen später geöffneten Dialog verändern.
Die detailseitige Aktion verbleibt bis zur Detailmigration am expliziten Adapter.

Speichern und Entfernen senden nach Persistierung den vorhandenen
`movie_subscriptions_update`-Vertrag. Die zuvor ausschließlich nachgelagerte
Qualitätsprüfung garantierte nach abgebrochenem HTTP-Request keine Aktualisierung.
Persistenzfehler erzeugen weiterhin keinen Erfolgssnapshot; Provider-, Qualitäts-,
Queue- und Löschentscheidungen bleiben unverändert im Backend.

Regressionen prüfen wiederholtes Mounten ohne doppelte Schreib-/Prüfaktionen,
unveränderte Speicherpayloads, sichtbare Fehler und Wiederherstellung, Entfernen,
Abbruch beim Schließen, Film-/Serien-Topic-Trennung und stabile Medienidentität.
Die Backendtests prüfen die persistierten Save-/Remove-Snapshots über Live-Ereignisse.


## Serienkalender

`calendar/state.js` besitzt den Server-Sendeplan, einen deduplizierten laufenden
Read und dessen Fehler-/Ladezustand. Die bisherige Anfrage unmittelbar nach der
Anmeldung bleibt als Bootstrap-Read erhalten. Die View wird erst beim Öffnen von
`#tab-kalender` gebunden; Navigation und Sessionende brechen einen verbleibenden
Read ab. Eine neue Mount-Phase lädt erneut, wenn zuvor kein Snapshot fertig wurde.
Es gibt keinen dauerhaften Intervall-Timer mehr: 15 Sekunden Transport-Timeout und
16 Sekunden Watchdog einschließlich Visibility-Prüfung leben nur im Request-Scope.
Auch ein nicht antwortender Transport beendet den Ladezustand; verspätete Antworten
nach Abbruch verändern weder Cache noch Ansicht.

`model.js` validiert Provider-Slugs, Bild-URLs und tatsächliche Kalenderdaten;
`storage.js` übernimmt die bestehenden Cache-/Filter-Schlüssel. Ein validierter
Snapshot ist höchstens 30 Tage als letzter verfügbarer Stand nutzbar. Filter bleiben
pro Benutzer gespeichert. Gesperrter Browser-Speicher blockiert den Start nicht.
Der lokale UI-Zustand umfasst Sprache, Status, Suchtext, Tag/Woche und Auswahl.
`view.js` besitzt ausschließlich den Kalender-Root und scoped Bildlistener; nach
jeder Darstellung werden die vorigen Bildlistener entfernt. Abo-Markierungen
werden aus dem aktuellen Abo-Snapshot abgeleitet und reagieren auf Live-Ereignisse,
statt alte persönliche Markierungen aus dem Kalender-Cache zu übernehmen.

`state.calendar`, das klassische Kalenderskript und sein globaler Safety-Timer sind
entfernt. Browser-Regressionsprüfungen decken wiederholtes Öffnen, Sprach-/Status-
und Suchfilter, Tages-/Wochenansicht, leere Ergebnisse, erhaltene Daten nach Fehlern,
Abbruch beim Verlassen und Live-Abo-Markierungen ab. Native Modultests prüfen
Request-Deduplizierung, Deadline, Cache-Validierung, Benutzertrennung und späte
Antworten. Vorhandene Backend-Sendeplan- und Provider-Session-Verträge bleiben
unverändert.


Die gemeinsame Katalog-Anreicherung liegt in `features/discovery/artwork.js`.
Sie verwendet den zentralen HTTP-Client, besitzt einen Session-Lifecycle und
akzeptiert zusätzlich ein AbortSignal des aufrufenden Features. Nach Abbruch
werden weder Metadaten noch Cache oder Darstellung verändert. Serien werden
weiterhin in Achtergruppen mit maximal drei Durchläufen angereichert; nur vom
Server als ausstehend gemeldete Titel werden wiederholt. Provider-verbindliche
Treffer übernehmen ausschließlich Cover und Hintergrundbilder. Die früheren
Wrapper in Bibliothek und globaler Suche entfallen; die Dubletten-Abstimmung
wird explizit injiziert. Klassische Aufrufer verwenden vorerst dünne Adapter.
Home-Datenbeschaffung und Reservoir-Aufbau liegen in `features/home/data.js`;
der bisherige Sieben-Tage-Cache mit Schlüssel `royal-home-cache-v5` in `cache.js`.
Zwei primäre, fünf sekundäre und zehn tiefere Katalogabrufe bleiben erhalten.
Ein paralleler Start teilt denselben laufenden Hauptabruf. Das Reservoir wartet
auf diesen Abruf und erweitert die Daten ohne erneutes Rendern der aufgebauten
Startseite. Der Film-Jellyfin-Abgleich bleibt vor der ersten vollständigen
Darstellung, der Serienabgleich im Hintergrund. Session-Ende und `pagehide`
beenden Requests und verzögerte Aufgaben; bfcache-Rückkehr setzt unterbrochene
Arbeit fort. Verspätete Antworten dürfen keinen neuen Lifecycle verändern.
Die vorherigen Loader-Wrapper in `store.js` und `ai-discovery.js` entfallen.
Die KI-Empfehlungsansicht liegt in `home/recommendations.js`. Persönliches Ranking,
Hero-Auswahl und tägliche Top 10 liegen in `taste-ranking.js`, `hero-selection.js`
und `daily-top.js`. Die drei entsprechenden klassischen Wrapper und ihr dynamischer
Skript-Loader sind entfernt. Funktionen werden nicht mehr nachträglich ersetzt.


## Einstellungen, Einrichtung und Anmeldung

`settings/index.js` koordiniert die bestehende Speicherfolge. Jeder Schritt prüft
seinen ursprünglichen View-Scope: Ein Seitenwechsel verhindert weitere Schreibaktionen
und späte Statusänderungen. Allgemeine Felder, Provider-Auswahl und Integrationsformulare
besitzen eigene Entwürfe. Serverantworten überschreiben zwischenzeitliche Eingaben nicht.
Die Provider-Auswahl wird mit der Einrichtung geteilt; dort gelten dieselben Sprach-,
Quellen- und Reihenfolgeregeln. `directory.js` verwendet den gemeinsamen Dialog und
bricht die vorherige Browse-Anfrage vor einem Ordnerwechsel ab.

`integrations/jellyfin.js` besitzt den Konfigurationssnapshot. Abo-Regeln lesen daraus
nur Benutzerkonfiguration und Standard-Löschregel. Die wiederverwendete Benutzerauswahl
kennt ihren eigenen Formular-Root; geheime Formularwerte werden nicht im App-Store
abgelegt. Seerr-, TMDB- und Telegram-Konfiguration bleiben getrennte Backendverträge.
`integrations/health.js` akzeptiert ausschließlich den expliziten Serververtrag
`integration_health.state`: healthy, degraded, offline, auth_failed, disabled oder unknown.
`api/integration_health.py` ergänzt diesen Vertrag additiv an den Modulantworten;
Fehlertexte und Jellyfin-Medienbesitz werden nicht als Health-Zustand interpretiert.

`settings/updater.js` abonniert die vorhandenen Live-Topics. Ein aktiver Installer
verwendet weiterhin das bestehende Fallback-Polling. Restart-Prüfungen laufen nur im
View-Scope und laden erst bei exakt passendem Ziel-SHA neu. Beim Unmount verschwinden
Timer, Requests und Subscriptions. `settings/account.js` besitzt Benutzerliste,
Benutzeraktionen, Passwortänderung und Session-Widerruf samt ihrer Requests.

`setup/index.js` besitzt Schritt, Sprachgeneration, einmaligen Bootstrap-Code und
Formularlistener. Secrets werden beim Unmount geleert. Übersetzungsantworten aus
einer alten Mount-Phase verändern den Assistenten nicht. `auth/index.js` hält den
Server-Anmeldestatus und veröffentlicht nur die Identität in `appStore`. Der
Login-Dialog besitzt einen eigenen Scope; Sessionablauf beendet die Anwendungsviews.
Das klassische Login- und Account-Skript sowie ihre Transportfassaden sind entfernt.

`home/recommendations.js` besitzt Kandidaten-Fingerprint und Empfehlungsantworten.
Verfeinerung läuft nur bei sichtbarer Startseite; Identitätswechsel verwirft alte
Ergebnisse. `settings/intelligence.js` besitzt KI-Konfiguration und Verbindungstest.
`search/index.js` startet ausschließlich bei expliziter Eingabe-Bestätigung und zeigt
Ergebnisse der vier Kataloge progressiv. Neue Suchanfragen, Schließen und Sessionende
brechen alte Requests ab. Der bisherige Suchdekorator wurde entfernt.

Zusätzliche Browserprüfung: `node tests/frontend/setup-browser.cjs` verwendet wie
`browser-smoke.cjs` ausschließlich abgefangene API-/WebSocket-Fixtures. Sie prüft die
Einrichtung einschließlich Quellenregeln, Pflichtfeldern, Jellyfin-Benutzer und
Bootstrap-Payload sowie erhaltene Jellyfin-Entwürfe und Request-Abbruch.


`profile/taste-onboarding.js` behält ausgewählte echte Katalogtitel über weitere
20er-Batches. Mindestens fünf Titel sind erforderlich. Kandidaten-Normalisierung
und Vielfalt liegen in `taste-candidates.js`, die Auswahlkarten im gemeinsamen
Media-Card-Modul. Der nicht per Escape schließbare Einrichtungsdialog verwendet
denselben Fokus-/Scope-Mechanismus wie andere Dialoge. Navigation des Browsers
beendet Listener, Frames und Schreibrequests; alte Antworten verändern keine
spätere Auswahl. Der Browser-Test prüft Batch-Auswahl, Entfernen, Mindestzahl,
Abbruch während des Speicherns und erneutes Öffnen ohne doppelte Aktionen.

`search/home.js` besitzt die kompakte Home-Suche mit unverändert maximal 36
Filmen/Serien. Der globale Suchbereich hat weiterhin keine solche Begrenzung.
Beide unterscheiden Ergebnislosigkeit von Transportfehlern. Die persönliche
Geschmacksauswahl teilt die laufenden Katalogabrufe von `home/data.js`, statt
per Timer auf deren Abschluss zu warten.

`integrations/catalog-jellyfin.js` hält Medienverfügbarkeit und Request-Versionen.
100er-Batches, Metadatenpriorität und Statusprojektion bleiben erhalten. Ein älterer
Batch darf einen neueren Status desselben Titels nicht überschreiben. Caller-Signal
und Session-Ende brechen Transport und nachfolgende Darstellung ab. Der globale
Home-Status-Cache ist entfernt. Das ist ausdrücklich kein Integrations-Health-Store.

`core/startup.js` koordiniert die einmalige Dateninitialisierung. Katalog-/Genre-
Daten gehören weiterhin ihren jeweiligen Diensten. `discovery/genres.js` besitzt
die Genreliste und erneuert sie nach einem Quellenwechsel. Das frühere Setup-Skript
ist vollständig entfernt. Ranking- und Feedback-CSS wird aus regulären Stylesheets
geladen; die dynamisch eingefügten Style-Tags entfallen.


## Trailer, Startseiten-Editor und Kartenbilder

`features/trailers/` besitzt Film-, Serien- und Vollbildplayer samt gemeinsamen
Ton-/Autoplay-Präferenzen. Jeder Player besitzt einen eigenen Scope: verzögerter
Start, YouTube-Abonnements, Fade-in und Lade-Timeout enden mit dem Player.
Nachrichten werden nach Origin und Quellfenster geprüft. Wiederholtes Rendern
startet denselben Trailer nicht erneut. Der Film-Load-Handler verwendet nun das
explizite Detail-Panel. Die alten Trailer-/Scroll-Skripte und der nachträgliche
Trailer-Wrapper in `store.js` wurden entfernt.

`home/layout-model.js` normalisiert bekannte Reihen und verhindert ein vollständig
leeres Layout. `home/layout.js` trennt den Server-Snapshot vom lokalen Entwurf.
Vorschau, Reihenfolge und Sichtbarkeit bleiben erhalten; Abbrechen verwirft nur
den Entwurf. Der gemeinsame Dialog übernimmt Fokus und Tastatur. Ein abgebrochener
Speichervorgang invalidiert den Snapshot, der beim nächsten Öffnen erneut geladen
wird. Spätere Änderungen während eines Speichervorgangs bleiben im Entwurf.

`shared/components/card-artwork.js` besitzt Lazy-Loading, Bild-Fallbacks und
Observer für gemeinsam verwendete Karten. Entfernte Bilder werden nicht weiter
beobachtet. `home/rail-renderer.js` aktualisiert bestehende Karten ohne unnötigen
DOM-Austausch und besitzt die Scroll-Listener und Frames der sichtbaren Startseite.
`home/card-dock.js` besitzt die schwebende Karten-Vorschau einschließlich Fokus,
Hover-Timern und abbrechbaren Trailer-Metadatenanfragen. Ein Seitenwechsel entfernt
das Dock und verhindert spätere Änderungen durch alte Antworten.

`integrations/resume.js` besitzt den Jellyfin-Abgleich nach Fokus-/Netzwerk-Rückkehr
oder Browser-Standby. Der 15-Sekunden-Takt erkennt ausschließlich Zeitsprünge;
ein normaler Tick startet keine Serveranfrage. Session-Ende entfernt alle Listener
und Timer, BFCache-Rückkehr bindet sie einmalig neu.


## Stimmungssuche, Sprachwahl und Katalogdienste

`features/mood/` trennt Auswahlregeln, Darstellung und Dialogablauf. Harte Genre-
Vorgaben bleiben unverändert. Der Dialog besitzt Fokusführung, Tastaturaktionen,
Metadaten-Anfragen und deren Zeitlimit. Schließen oder Session-Ende verhindern
späte Ergebnis- und Cache-Änderungen.

`home/discovery-policy.js` besitzt persönliche Expositionsdaten, Ablaufregeln und
Diversitätsauswahl. Hero und Reihen melden sichtbare Titel explizit. Das frühere
Installationsskript überschreibt keine Ranking-Funktionen mehr; Tagesranking und
Geschmacksranking werden direkt zusammengesetzt.

`media-details/language.js` vereinheitlicht Sprachdaten, Kennzeichnungen und die
Sprachauswahl vor einem Download. Ein neuer Dialog beendet den vorherigen;
Navigation, Escape und Session-Ende lösen offene Auswahl-Promises auf. Die Styles
liegen unverändert in `styles/movie-language.css`. `store.js` enthält ausschließlich
den noch migrierbaren Ausgangszustand.

`discovery/catalog-refresh.js` bindet Film- und Serien-Aktualisierungen an die
sichtbare Ansicht. Timer, Requests und verspätete Antworten enden mit deren Scope.
Bereits geladene Folgeseiten bleiben beim Einfügen neuer Filme erhalten.
`poster-preload.js` begrenzt parallele Bildabrufe und beendet auch blockierte Bilder
bei Navigation oder Zeitüberschreitung. Sichtbare Katalogkarten verwenden den
zentralen Bilddienst mit sofortigem Laden ihrer kleinen Vorschaubilder.

`catalog-metadata.js` besitzt 12er-Batches mit drei parallelen Workern und
abbrechbaren Wiederholungen. Alte Generationen dürfen weder Cache noch Darstellung
aktualisieren. `catalog-seed.js` übernimmt Home-Vorschauen; die jeweiligen Anbieter
bleiben für vollständige Kataloge und Pagination zuständig.

`catalog-identity.js` führt dieselben Medien über Anbietergrenzen zusammen und
bewahrt dabei Priorität, Sprachen und Jellyfin-Status. Die Ergebnisse werden
explizit vor der Darstellung bereinigt. Die nachträglichen globalen Funktions-
überschreibungen aus `screens/library.js` und `catalog-runtime.js` sind entfernt.
Die klassischen Katalog-Presenter und deren Zustandsobjekte bleiben als nächste
Migrationsschritte offen; diese Teilmigration ist noch kein Gesamtabschluss.


`discovery/movie-browse.js` und `series-browse.js` besitzen Such-/Listenabrufe,
Pagination, Such-Rückkehrzustand und die jeweiligen Filter-/Such-Listener. Neue
Abrufe und Navigation brechen alte Requests ab; deren Antworten dürfen keine
Darstellung mehr auslösen. Die Serien-Alphabetleiste wird einmal je Mount gebunden.
Provider-Suche für Filme behält das bisherige fehlende Zeitlimit. Die globalen
Presenter-Brücken bestehen während der weiteren Detailmigration fort.


`discovery/movie-filters.js` besitzt den lokalen Filterzustand und projiziert die
sichtbaren Karten ohne Änderung der Katalogergebnisse. Das alte Filter-Skript ist
entfernt. `media-details/movie-loader.js` und `series-loader.js` besitzen die
Metadaten-/Anbieterabfragen für geöffnete Details. Schließen verwirft alte Antworten
vor Cache- oder DOM-Änderungen. Das Öffnen abonnierter Serien nutzt denselben
Lebenszyklus; die getrennte Monster-TMDB-Route bleibt unverändert erhalten.


`media-details/series-checks.js` besitzt parallelen Jellyfin-Status, ergänzende
Seriendaten und Sprachprüfungen in 30er-Batches. Modal-Schließen und Navigation
beenden alle zugehörigen Requests. Generationen liegen im Dienst statt im globalen
Serienzustand. Abgebrochene Sprachprüfungen ändern keine Auswahl oder Statuszeile.
`series-api.js` bündelt die vorhandene Trennung normaler und spezieller Serienrouten;
die abgelösten API-Fassadenmethoden sind entfernt.


`discovery/anime.js` besitzt Katalog, Suche, Spuren, Episodenseiten und Auswahl als
lokalen Zustand. Katalogansicht und Detaildialog haben getrennte Scopes; auch aus
Home geöffnete Anime-Details funktionieren ohne gemounteten Anime-Katalog.
Karten-/Episodenaktionen werden delegiert. Schließen beendet Detailabrufe; Navigation
beendet Katalog- und Statusabrufe. Queue-Antworten aktualisieren den gemeinsamen
Server-Snapshot, verändern aber keine später geöffnete Auswahl. Verbleibende
Konsumenten lesen über den Feature-Dienst; globale Anime-/AniWorld-Zustandsobjekte
sind entfernt.
Die ungenutzten klassischen Katalog-/TMDB-/Anime-API-Methoden sind entfernt.


`discovery/aniworld.js` besitzt Katalogfilter, Pagination, Poster-Cache, Sprachspur,
Staffel und Auswahl. Ansicht und Detaildialog haben getrennte Scopes; Posterjobs
enden mit ihrer Ansicht oder einer neuen Filterabfrage. Der vorhandene statische
AniWorld-Aufbau steht jetzt unverändert in `index.html`, statt beim Laden eines
klassischen Skripts eingefügt zu werden. Der Infinite-Scroll-Dienst besitzt den
Retry-Listener allein. Alte AniWorld-API-Fassaden sind entfernt.


`profile/taste.js` besitzt persönlichen Cache, Synchronisierung, Feedback,
Interaktionssignale und Reset. Requests gehören zur Sitzung und prüfen vor späteren
Cache-/UI-Änderungen zusätzlich die Benutzeridentität. Die vorhandene lokale
Rückfallebene und optimistische Bewertung bleiben erhalten; Serverantworten ersetzen
den Snapshot. Feedback-/Reset-Listener werden einmalig gebunden und beim Session-Ende
entfernt. Verweigerter Zugriff auf Browser-Speicher bleibt abgefangen.


`home/catalog.js` besitzt Inhaltsidentitäten und Reihenfolge, einschließlich expliziter
Filmreihen-Identität. `home/lanes.js` stellt die vorhandenen Programme zusammen;
`home/presenter.js` besitzt Shuffle, Tageswechsel und Renderstatus. Das globale
Home-Zustandsobjekt ist entfernt. Shuffle-/Resize-Listener gehören zur sichtbaren
Home-Ansicht. `home/cards.js` verbindet gemeinsame Karten mit den expliziten
Feature-Aktionen. Filmreihen überschreiben keine globalen Home-Funktionen mehr.
Der Jellyfin-Dienst filtert Reihen selbst und erhält damit alle Request-Optionen
inklusive des Abbruchsignals. `search/support.js` kapselt persönliche Suchhistorie
und Eingabehilfen; ungenutzte alte Vorschlagsrenderer sind entfernt.

`collections/index.js` besitzt Filmreihen-Dialog, Auswahl und Verfügbarkeitszustand.
Detail-, Jellyfin- und Anbieterabrufe enden beim Schließen oder Ersetzen der Reihe.
Queue-Mutationen gehören zur Sitzung; ihre Antworten dürfen den gemeinsamen
Queue-Snapshot aktualisieren, aber keine spätere Detailauswahl überschreiben.
Doppelte Queue-Klicks werden abgefangen. Kartenaktionen werden über schwach
referenzierte Callbacks delegiert; Sitzungsende entfernt Listener und Requests.
Der Lebenszyklustest prüft geschlossene Abrufe und die Isolation später Antworten.


Film- und Serienzustand werden separat durch `discovery/movie-state.js` und
`discovery/series-state.js` erzeugt. Katalog-, Cache- und Auswahlkonsumenten erhalten
nur ihren Feature-Zustand; das alte globale Sammelobjekt enthält diese Bereiche
nicht mehr. Die verbleibende klassische Brücke liest dieselben expliziten Instanzen.
`movie-presentation.js` und `series-presentation.js` besitzen die bestehenden
Katalog-/Detailrenderer. Ansichtswechsel entfernen die delegierten Katalogaktionen;
Detailaktionen gehören separat zur Sitzung, sodass Home weiterhin Details öffnen kann.

`downloads/movies.js` vereinheitlicht Film-Queue-Kommandos, Vorprüfung, Sprach-/Quellwahl
und Downloadfeedback. `downloads/outcome.js` interpretiert übersprungene Queue-Einträge.
`media-details/series-episodes.js` besitzt Episodenregeln, Auswahl und Serien-Queue-Kommandos.
Anfragen gehören zur Sitzung, verhindern doppelte Mutationen und aktualisieren nach
Detailwechsel keine fremde Auswahl. Geschmackssignale beziehen sich auf den Titel,
für den die Anfrage gestartet wurde. Abbruch-/Antwortisolation ist funktional getestet.

`shared/components/result-card.js` vereinheitlicht Posterwechsel und Tastaturaktionen
für Film-/Serienkarten. Pro sichtbarem Katalog gibt es einen Scope; Decode-, Frame-,
Transition- und Timerarbeit wird bei Navigation beendet und bei Rückkehr fortgesetzt.
`integrations/movie-status.js` bündelt Film-Verfügbarkeitsprüfungen mit Abbruch beim
Schließen; ein alter Worker kann keinen neuen Worker freigeben.
`media-details/series-status.js` kapselt die Serien-Statusdarstellung.
`media-details/discovery.js` ersetzt beide alten Detail-Discovery-Skripte mit gemeinsamen
Empfehlungs-/Trailerkarten und getrennten Film-/Serieninformationen.

## Overnight-Zwischenstand

Dieser Zwischenstand ist bewusst noch keine abgeschlossene Migration. Die alte
HTTP-Fassade `web/api.js` und das globale Übersetzungsskript wurden entfernt.
`core/shell.js` besitzt die Shell-Ereignisse, `core/localization.js` die
Übersetzungs-Lebensdauer und `downloads/sync.js` die Queue-Synchronisierung.
Offen bleiben die letzten klassischen Shell-/Brückenskripte und die abschließende
Bereinigung dieser während der Migration fortgeschriebenen Dokumentation.

Prüfung des Zwischenstands: 136 JavaScript-Tests bestanden; 821 Python-Tests
bestanden, 10 übersprungen. Zwei Windows-spezifische Fehler (POSIX-Dateirechte
und `/external`-Pfadnormalisierung) wurden auch gegen das unveränderte
`origin/overnight` reproduziert. Browser- und Einrichtungstests bestanden;
2398 Shell-Elemente zeigten bei 1440 und 390 Pixeln dieselben berechneten CSS-Werte
wie vor der Migration. JavaScript-Syntaxprüfung, Ruff-Korrektheitsprüfung und
Security-Regressionsscan bestanden. Die Linux-CI bleibt für die Plattformprüfung
maßgeblich.
