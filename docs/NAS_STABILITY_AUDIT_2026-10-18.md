# NAS-Ausfälle: Untersuchung vom 18.10.2026

## Ergebnis und Stand

Weitere konkrete Blockade- und Überlastpfade gefunden und lokal korrigiert.
Die bestehenden Korrekturen für Watchlist-GET und WebSocket-Authentifizierung
deckten diese Pfade noch nicht ab. Ein einzelner langsamer NAS-Zugriff konnte
weiterhin den einzigen HTTP-Event-Loop anhalten.

Das NAS meldete Version **2.0.0**, Kanal **Overnight**, Build
`235de75a0275173cd09329d2a692612db2e4eb55`. Der lokale Ausgangscommit ist
`812236f52e08db9957575dbc3c57c84849368f16`; die Untersuchung betrifft den
Arbeitsstand einschließlich bereits vorhandener lokaler Änderungen.
Der Update-Installer auf dem NAS war bei der Abfrage inaktiv.
Der gemeldete NAS-Commit wurde in der Nachprüfung aus dem konfigurierten
Git-Remote geladen. Die betroffenen Backend-Dateien stimmen bytegenau mit dem
lokalen Ausgangscommit überein, unter anderem Administration, Queue, Speicher,
Broadcast, Browser-Sicherheitsadapter und CDP-Proxy. Die Fehlerpfade sind damit
auch im Quellstand des gemeldeten NAS-Builds vorhanden. Eine separat aus dem
Container ausgelesene Quelltextkopie liegt nicht vor.

**Die Korrekturen sind noch nicht auf dem NAS installiert.** Keine Downloads,
Einstellungen, Updates oder Neustarts auf dem NAS ausgelöst. Diagnosesitzungen
anschließend abgemeldet; Zugangsdaten sind nicht in den Berichten gespeichert.

## Befunde und Korrekturen

| Bereich | Schwachstelle und Auswirkung | Lokale Korrektur |
| --- | --- | --- |
| Einstellungen, UI-Sprache, Quellenstatus, Seerr | Direkte Datei-/Snapshot-Aufrufe warten auf Sperren, die Hintergrundschreibvorgänge einschließlich `fsync` halten. Das stoppt auch unabhängige HTTP-/WebSocket-Arbeit. | Lesen, Anwenden und lockabhängige Antworten in Worker ausgelagert. |
| Quellenpriorität und Anime | `provider_priority()` und AniWorld-Vorabprüfungen lesen Provider-Health direkt im Loop. Dessen Sperre schützt auch persistente Health-Schreibvorgänge. | Auch Vorabprüfungen und Prioritätsauflösung außerhalb des Loops. |
| Speicherstatus, Scan, Verschieben, Bereinigung | Argumente wie `_media_paths()` und `load_storage_locations()` wurden vor `run_in_threadpool(...)` ausgewertet. Der sichtbare Threadpool-Aufruf schützte diese Dateizugriffe nicht. | Gesamten Aufruf einschließlich Argumentvorbereitung ausgelagert. |
| Queue-Bedienung | Fortsetzen wartender Jobs persistierte synchron. Nach Hinzufügen, Abbruch, Retry und Umordnen wurden weitere Queue-Snapshots direkt im Loop gebaut. | Persistenz, Sperren und abschließende Snapshots ausgelagert. |
| Modullaufzeit, Integrationen | `reconcile()` kann Worker stoppen und auf deren Ende warten. Aufrufe nach Änderungen an Telegram, Jellyfin, Seerr, Updates und Intelligence liefen im Loop. Update-Status baut außerdem einen dateiabhängigen Broadcast. | Lifecycle- und Statusänderungen in Worker ausgelagert. |
| Setup und Übersetzung | Zusätzliche Bootstrap-, Konto-, Sitzungs- und Konfigurationsprüfungen konnten synchron warten. | Middleware, Setup-Transaktion und Übersetzungsberechtigung entsprechend ausgelagert. |
| Releases | Die vermeintlich kurze Verfügbarkeitsprüfung greift auf den gesperrten, persistenten Release-Store zu. | Auch diesen Einstieg ausgelagert. |
| Katalog-/Personensuche | Langsame externe Aufrufe konnten den gemeinsamen HTTP-Pool mit Anmeldung und statischen Dateien belegen. Browser-Abbruch beendet laufende Threads nicht. | Eigener Pool: acht Worker, maximal 24 offene Aufgaben. Überlast liefert `503 browse_busy`. Laufende abgebrochene Aufgaben behalten ihren Platz bis zum tatsächlichen Ende. |
| Poster | Acht Worker begrenzten nur parallele Ausführung; die Warteschlange blieb unbegrenzt. Gleiche URLs konnten mehrfach geladen werden. | Höchstens 32 offene URLs, identische laufende Abrufe geteilt. Einzelner Client-Abbruch beendet keinen geteilten Abruf. HTTP-Wartezeit zehn Sekunden. |
| Hintergrundkataloge und Metadaten | Nach Ablauf kurzer HTTP-Budgets liefen Futures weiter. Unterschiedliche Seiten/Anfragen konnten unbegrenzt weitere Futures hinzufügen. | Je Film-/Serienkatalog höchstens 64 offene Quellseiten, je acht Prefetch-Aufgaben; höchstens 128 offene geteilte TMDB-Metadatenaufgaben. |
| Wartung und Shutdown | Eine Ausnahme konnte die periodische Cache-/Modulwartung dauerhaft beenden. Worker-/Browser-Stopp lief teilweise im Loop; Cleanup war nicht durch `finally` geschützt. | Fehler pro Wartungsschritt protokollieren und nächsten Zyklus fortsetzen; Cleanup in `finally`, Tasks abwarten, blockierende Stopps auslagern. |

Bei Kapazitätsgrenzen bleiben Katalog-/Serienprüfungen ausdrücklich unvollständig
oder ausstehend. Fehlende Kapazität wird nicht als bestätigte Abwesenheit eines
Mediums gespeichert. Laufende Netzwerk-/Dateioperationen lassen sich in Python
nicht sicher zwangsweise beenden; ihre Belegung bleibt deshalb mitgezählt.

## Reproduktion mit echtem Routencode

Vergleich der ursprünglichen Handler aus dem lokalen Ausgangscommit und der
korrigierten Handler, mit isolierten Daten und 300 ms künstlicher Verzögerung
im jeweiligen synchronen Lesezugriff. Gemessen wird die Verzögerung einer
parallel geplanten unabhängigen Health-Aufgabe auf demselben Event-Loop.

| Handler | Vorher | Nachher |
| --- | ---: | ---: |
| Speicherstatus | 307,48 ms | 0,12 ms |
| Seerr-Konfiguration | 300,47 ms | 0,10 ms |
| UI-Konfiguration | 300,46 ms | 0,13 ms |

Das belegt den Blockademechanismus. Die Werte sind lokale synthetische
Reproduktionen und keine Messung eines behobenen NAS-Produktionsausfalls.
Rohdaten: `artifacts/nas-stability-2026-10-18-reproduction.json`.

## NAS-Stichprobe

24 normale Leseanfragen gegen zwölf Bereiche, höchstens zwei gleichzeitig:
Queue, Watchlist, Film-Abos, UI-/Pfad-/Quellen-/Seerr-/AI-Konfiguration,
Quellenstatus, Home-Layout, Speicherstatus und Module.

- 24 von 24 Antworten: HTTP 200.
- Langsamste Antwort: Speicherstatus, 54,6 ms.
- Zwei parallel erfasste Health-Antworten: beide 200, maximal 22,7 ms.
- Die Stichprobe war sehr kurz und reproduzierte keinen sporadischen Ausfall.

Rohdaten ohne Antwortinhalte oder Sitzungstoken:
`artifacts/nas-stability-2026-10-18-live.json`.

## Diagnose für den nächsten Ausfall

Neu: authentifizierte GET-Routen `/api/diagnostics/runtime` und
`/api/v1/diagnostics/runtime`. Der bestehende öffentliche Health-Inhalt bleibt
unverändert. Die neue Diagnose enthält:

- Prozess-ID, zufällige Instanzkennung, Startzeit und Laufzeit;
- Anzahl und maximale Dauer beobachteter Event-Loop-Blockaden;
- letzten Blockadestack mit höchstens zwölf Datei-/Funktions-/Zeilenangaben;
- Python-Threadanzahl sowie unter Linux RSS-/Spitzenspeicher, native Threads
  und offene Dateideskriptoren;
- Container-Speicher unter cgroup v1 und v2 einschließlich jeweils verfügbarer
  OOM-Zähler. Allokationsfehler unter v1 werden separat ausgewiesen.

Ein separater Watchdog-Thread protokolliert Blockaden auch während der Loop
stillsteht. Keine lokalen Variablen, Quelltextzeilen oder Zugangsdaten im Stack.
Eine Warnung pro zusammenhängender Blockade begrenzt das Logvolumen.
Die OOM-Zähler betreffen die Container-cgroup und beweisen allein keinen
Absturz dieses Python-Prozesses. Nicht verfügbare Zähler werden nicht als null
ausgegeben. Ein v1-Allokationsfehler ist ausdrücklich kein nachgewiesener OOM-Kill.

## Nachprüfung: Live-Updates und Browser-Lebenszyklus

Drei zusätzliche Fehlergruppen wurden korrigiert:

1. **Unbegrenzter Übergang von Worker-Threads zum Event-Loop.** Ein Broadcast
   erzeugte bislang für jedes Ereignis einen eigenen `call_soon_threadsafe`-
   Callback. Die Begrenzung pro WebSocket-Client griff erst nach Verarbeitung
   dieser Callbacks. Bei einem hängenden Loop konnte daher davor beliebig viel
   Arbeit samt Nutzdaten liegen bleiben. Der neue Übergang puffert höchstens
   256 Ereignisse und plant nur einen Drain-Callback ein. Er verarbeitet bis zu
   32 Ereignisse pro Durchlauf und gibt den Loop dazwischen frei. Bei Überlauf
   werden bestehende Verbindungen mit 1013 geschlossen; Browser und native
   Clients können dadurch ihren Zustand neu laden. Ein Regressionstest erzeugt
   10.000 Ereignisse bei stillstehendem Loop und weist einen einzelnen Callback
   statt 10.000 nach.
2. **Hängende oder still ausgefallene WebSockets.** Das Schließen eines langsamen
   Clients hatte keine Frist. Zudem wurde nach einem Sendefehler nur die interne
   Registrierung entfernt; eine noch offene Empfangsseite konnte für die UI
   weiter verbunden erscheinen. Close ist jetzt auf zwei Sekunden begrenzt,
   und auch Sendefehler schließen die Verbindung zur Neusynchronisierung.
3. **Ressourcenreste nach Browserfehlern.** Neu angelegte Remote-Tabs wurden bei
   fehlgeschlagener CDP-Initialisierung noch nicht vom aufrufenden Runtime-Objekt
   besessen und deshalb nicht geschlossen. Auch unvollständige Tab-Antworten
   mit vorhandener ID werden jetzt aufgeräumt. Der CDP-Proxy schließt seine
   Upstream-Verbindung nun bei fehlerhafter Handshake-Weiterleitung und bei
   späteren Fehlern, einschließlich fehlgeschlagener Thread-Erzeugung.

Die Ressourcenfehler wurden mit simulierten Verbindungs-, Konfigurations- und
Thread-Erzeugungsfehlern geprüft. Kein echter Browser musste dafür auf dem NAS
gestartet oder beendet werden.

## Erweiterte Live-Messungen

Auf dem unveränderten NAS-Build wurden zusätzlich gemessen:

| Prüfung | Stichprobe | Ergebnis |
| --- | --- | --- |
| Liveness über 180,2 Sekunden | 350 Health-Anfragen | alle 200; Median 2,6 ms, P95 5,8 ms, Maximum 74,1 ms |
| Normale Bedienabfragen währenddessen | 90 Anfragen | alle 200; Median 4,95 ms, P95 26,0 ms, Maximum 151,7 ms |
| LAN gegen öffentliche Domain | 20 gleichzeitige Paare | beide Wege vollständig 200; Maximum LAN 27,0 ms, öffentlich 427,9 ms |
| Film-/Serien-/Anime-Katalog und Details | fünf Anfragen | Kataloge und Serien-Detail 200; progressive Filmprüfung erwartungsgemäß 202 |
| Health während dieser Katalog-/Detailaufrufe | 19 Anfragen | alle 200; Maximum 390,8 ms |

Die abgefragten Queue-Snapshots enthielten während der längeren Messung keine
Jobs. Das war somit kein Lasttest mit laufenden Downloads. Der gemeldete 502
wurde auch bei diesen Stichproben nicht reproduziert; aus den Health-Antworten
allein lassen sich historische Neustarts oder OOM-Ereignisse nicht ableiten.

Rohdaten: `artifacts/nas-stability-2026-10-18-extended-live.json`,
`artifacts/nas-stability-2026-10-18-proxy-comparison.json` und
`artifacts/nas-stability-2026-10-18-browse-live.json`.

## Prüfung und verbleibende Grenzen

- Letzter breiter isolierter Offline-Lauf: **1.815 bestanden**, 20 übersprungen,
  acht gezielt abgewählt. Nach den letzten WebSocket-Anpassungen weitere
  20 gezielte Tests bestanden. Zusätzlich 123 Frontend-Tests für Kernabläufe,
  Detail-Loader und Abo-Zustände bestanden.
- Separat auf dem aktuellen `overnight`-Stand vorbereiteter Stabilitäts-PR, ohne
  parallele Huhu-Änderungen: **1.793 bestanden**, 20 übersprungen, acht abgewählt.
  Dieselben 123 Frontend-Tests bestanden auch in diesem isolierten Checkout.
- Unter Windows ausgenommen: Linux-Runner mit `resource`, sechs Symlinkfälle
  ohne benötigte Windows-Berechtigung sowie zwei Prüfungen für POSIX-Dateimodus
  und POSIX-Pfaddarstellung. Diese Linux-Prüfungen bleiben für die CI erforderlich.
- Projektweiter Ruff-Korrektheitscheck und Security-Regressionsscan bestanden.
- Bandit 1.9.4 für den Anwendungscode bestanden; lokale alte Runtime-Releases,
  deren Fremdbibliotheken, Tests und Artefakte wurden dabei ausgeschlossen.
- Tests umfassen zusätzlich bestehende Queue-, Persistenz-, Recovery-, Quellen-,
  Download-, Sprach-, Speicher-, Modul-, Integrations- und API-Verträge.
- Ausgabedateien des breiten Nachlaufs:
  `artifacts/nas-stability-2026-10-18-followup-tests.log` und `.xml`.
  Frontend: `artifacts/nas-stability-2026-10-18-frontend.log`.

Die Web-API liefert auf diesem installierten Stand keine Docker-Exitcodes,
Restart-Zähler, Host-Kernel-Logs oder historische Proxy-Logs. Ob die gemeldeten
502 zusätzlich durch OOM, Container-Neustarts, den Reverse Proxy oder einen
Tunnel verursacht wurden, ist daher weiterhin offen. Die neuen Diagnosen und
die Container-/Proxy-Logs müssen nach Installation beim nächsten Ereignis
zeitlich abgeglichen werden. Eine Garantie, dass alle NAS-Ausfälle beseitigt
sind, lässt sich aus Codeprüfung und einer kurzen Live-Stichprobe nicht ableiten.
