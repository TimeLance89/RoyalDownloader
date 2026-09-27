# Frontend Performance – Messprotokoll

Ausgangspunkt und Messgrenzen: [Baseline](FRONTEND_PERFORMANCE_BASELINE.md).
Implementierter Stand und geprüfte Phasen; die Freigabe erfolgt über die verpflichtenden CI-Gates in PR #364.

## Abschlussmessung auf dem ursprünglichen Windows-Testhost

Frontend-Quellstand `1c9ec4e`, Chromium 151.0.7922.34 / Playwright 1.62.1,
drei unabhängige Browserstarts je Profil. Dieselben Viewports, DPR, Daten und
Messdefinitionen wie in der Baseline; Rohwerte: [result.json](performance/result.json).

| Profil | Viewport | DOM | volle/logische Cards | Initial ms | Long Tasks | TBT ms | LCP ms | Event max ms | Layout ms | Script ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| desktop | 1440×1000 | 4640 | 137 / 97 | 55.4 | 4 | 98 | 3184 | 72 | 30.1 | 24.8 |
| desktop-4x | 1440×1000 | 4640 | 137 / 97 | 313 | 8 | 805 | 4164 | 96 | 164.7 | 127.7 |
| desktop-6x | 1440×1000 | 4640 | 137 / 97 | 548.5 | 18 | 1616 | 5756 | 136 | 278.4 | 199.3 |
| mobile-4x | 390×844 | 4360 | 117 / 97 | 285.2 | 6 | 650 | 3892 | 72 | 144.6 | 118.9 |

Alle 97 logischen Rail-Einträge werden zusätzlich aus den tatsächlich gerenderten
Card-Schlüsseln gezählt. Volle Cards: Desktop −46,7 %, Smartphone −54,5 %.
Gesamte DOM-Elemente: Desktop −26,6 %, Smartphone −31,0 %.
Layout-/Style-Anzahl, Script-Evaluation, Image-Decode und Heap stehen für jeden
Einzellauf im JSON. SVG-Decode 0 und GC-abhängige Heap-Werte sind keine Qualitätsgates.
Windows-Long-Task-Anzahl und LCP verbessern sich nicht in jedem Profil; die
gepaarte Linux-CI-Kontrolle unten trennt Host-Schwankungen von Rendering-Kosten.

## Phase B – native Touch-Steuerung

- Geschlossener mobiler Menü-Scrim respektiert `hidden`. Die bisher versehentlich
  sichtbare Abdunklung und Eingabesperre entfallen. Offenes Menü unverändert.
- Touch/Pen normalisieren erst nach `scrollend` bzw. 180 ms Ruhe, niemals während
  des Fingerkontakts. `pointercancel` beim Beginn nativen Scrollens beendet keine Geste.
- Swipe-Erkennung unterdrückt versehentliche Card-Klicks, ohne native Bewegung zu verhindern.
- Ein echter Cover-Tap deckte zusätzlich eine verschattete `coverUrl`-Funktion auf;
  die lokale Poster-Variable ist jetzt eindeutig benannt.
- 390×844, 430×932 und 768×1024: beide Swipe-Richtungen, schnelle Swipes, Settle,
  vertikales Seiten-Panning, Detail-Tap und Orientation-Wechsel erfolgreich.
  Keine JS-Schreibzugriffe auf `scrollLeft` während Fingerkontakt.
- Tab-Position und Loop-Seam werden in Phase C zusätzlich anhand logischer Anker geprüft.

Rohmessungen: [Phase B](performance/phase-b.json), [Touch](performance/mobile-phase-b.json).
Unverändert 97 logische Einträge, 257 vollständige Cards, 6320 DOM-Elemente.
Noch keine Performanceverbesserung durch DOM-Reduktion beansprucht.

### Bewusste CSS-Ausnahme

Der eingefrorene Vor-Refactor-Stand bleibt unverändert. Im CSS-Vergleich erhält
nur dessen **geschlossener** Menü-Scrim dieselbe `hidden`-Korrektur. Damit wird
die beabsichtigte Oberfläche verglichen; die fehlerhafte Abdunklung ist ausdrücklich
kein zu erhaltendes Designmerkmal. Alle übrigen 2398 Elementvergleiche bleiben strikt.

## Phase C – begrenzte Carousel-Ränder

Alle Original-Cards bleiben im DOM und per Tastatur zugänglich. Randkopien decken
zusammen einen Viewport plus zwei Card-Abstände ab. Identische Originale werden
beim Aktualisieren wiederverwendet. ResizeObserver passt die Puffer an und erhält
die logische Position; laufende Touch-Gesten werden zuerst beendet.

| Profil | Volle Cards vorher → nachher | Renderzeit-Verhältnis | Script-Zeit-Verhältnis | TBT-Verhältnis |
|---|---:|---:|---:|---:|
| Desktop | 257 → 137 (−46,7 %) | 0,655 | 0,523 | 0,504 |
| Desktop 4× | 257 → 137 | 0,722 | 0,658 | 0,637 |
| Desktop 6× | 257 → 137 | 0,735 | 0,661 | 0,734 |
| Mobile 4× | 257 → 117 (−54,5 %) | 0,639 | 0,707 | 0,634 |

Je drei unabhängige Messungen; Verhältnis der Mediane zur ursprünglichen Baseline,
kleiner ist besser. Weiterhin 97 logische Einträge. DOM: 4640 Desktop / 4360 Mobile
statt 6320. Rohwerte mit allen Kennzahlen: [Phase C](performance/phase-c.json).

Beide Schleifenränder zeigen vor/nach Korrektur dieselben sichtbaren Titel,
Positionsabweichung höchstens 1 CSS-Pixel. Endlose Rails verwenden freies natives
Scrolling: erneutes CSS-Snapping nach einem Wrap würde die Endposition versetzen.
Endliche Ranking-Rails behalten ihr bisheriges Proximity-Snap. Keine Änderung an
Card-Größe, Typografie, Farben, Blur oder Animationen.

Alle drei Touch-Viewports: Tab-Positionsabweichung **0 px**, keine JS-Scrollwrites
während Fingerkontakt, keine Swipe-Klicks. [Touch-Rohdaten](performance/mobile-phase-c.json).

21 Screenshot-Vergleiche der sieben gefüllten Rails bei Desktop, Smartphone und
Tablet: höchstens **0,259 %** abweichende Pixel, darunter keine strukturelle Änderung.
Vor dem Screenshot wird ausschließlich die Subpixel-Rasterphase unter 1 CSS-Pixel
ausgeglichen; vorher werden reale Positionen, exakte Card-Maße, Schrift und Inhalt
separat geprüft. Die ursprünglichen Referenzdateien bleiben unverändert.
[Visuelle Messungen](performance/visual-phase-c.json).

## Phase D – Offscreen-Abschnitte

`content-visibility:auto` wird nur weit außerhalb des Viewports auf den Rail-
Abschnitt gesetzt. Eine 900-px-IntersectionObserver-Zone nimmt sichtbare/nahe Rails
aus der Paint-Containment-Darstellung heraus. So bleiben Schatten und Textrasterung
sichtbarer Cards erhalten. Die Intrinsic-Höhe stammt aus ResizeObserver; dessen
Schreibzugriffe laufen in einem eigenen Frame. Alle Observer gehören zum Home-Scope.

Verworfene Versuche: Skipping direkt am Scroll-Container verlor Scrollpositionen;
dauerhaftes Paint-Containment sichtbarer Rails veränderte Kantenrasterung. Beide
wurden durch Touch-/Bildtests erkannt und nicht übernommen.

[Identischer Hauptbenchmark](performance/phase-d.json). Initiales Vermessen der
Intrinsic-Höhen kostet zusätzliche Layout-Arbeit gegenüber Phase C; der gezielte
[Offscreen-Test](performance/offscreen-phase-d.json) zeigt den Gegenwert: Bei 6× CPU
verursachen 40 Hintergrund-Textupdates **0 Layouts / 0 ms** statt 40 Layouts /
206–219 ms ohne Skipping. Die Dokumenthöhe bleibt dabei unverändert. Das ist ein
synthetischer Hintergrund-Update-Test, keine Behauptung über sämtliche App-Aktionen.

[21 Bildvergleiche](performance/visual-phase-d.json): exakte Maße/Schriften/Inhalte,
höchstens ein CSS-Pixel positionsbedingte Rasterabweichung. Das Protokoll enthält
ungefilterte Pixelunterschiede (`rawRatio`) und den Rest nach symmetrischer
Ein-Pixel-Kantentoleranz (`ratio`, maximal 0,00142 %). Die Toleranz verbirgt keine
Flächen-/Farbänderungen; ein separater Test schützt vor entfernten Komponenten und
geänderten Füllfarben. Referenz-Commit und CSS-Baseline bleiben unverändert.

## Effekte, Artwork, Fonts und optionale Qualitätsmodi

Der [Browser-Audit mit echten Google Fonts](performance/effects-fonts.json) erfasst
die sichtbaren Filterflächen: Topbar 120960 px² / Blur 22 px, Programm 177913 px² /
18 px, Queue 141120 px² / 18 px. Das sind Flächen, **keine GPU-Zeitmessungen**.
Ohne isolierten Nachweis gleicher Optik wurden keine Blur-, Schatten-, Kontrast-
oder Sättigungswerte geändert. Offscreen-Arbeit entfällt unabhängig von der GPU-Klasse.

Vier Font-Familien bleiben bestehen. Der Browser lädt nur benötigte Faces; beim
Home-Audit waren neun Faces geladen, alle mit `font-display: swap`. Das CSS nutzt
auch Zwischengewichte wie 620, 650, 680, 720 und 750 sowie schwerere Mono-Schriften.
Eine Streichung anhand nur der Startseite wäre kein belastbarer Nachweis ungenutzter
Varianten. Preconnect, Fallbacks, Gewichte und Typografie bleiben deshalb unverändert.
Der Audit weist keine isolierte fontbedingte CLS-/First-Paint-Verbesserung nach.

Artwork behält Auflösung, `lazy`, `async` und die bisherigen IO-Margins. Durch
weniger Kopien werden bereits weniger Images/Observer-Ziele angelegt. Ohne einen
Benchmark mit realen JPEGs und unterschiedlichen Netzbedingungen wäre ein engeres
Preload-Fenster eine unbelegte Verschlechterungsgefahr. Keine neue Qualitätsstufe
oder Hardware-Heuristik: Die strukturellen Einsparungen gelten auf allen Geräten.
Hero-Rotation pausierte bereits bei verstecktem Tab; diese bestehende Funktion bleibt.

## Phase E – gebündelte Layout-Arbeit

Artwork sammelt erst alle relevanten Card-Rechtecke aller wartenden Rails und
schreibt danach `src`, Klassen und Prioritäten. Bereits gestartete Bilder benötigen
keine erneute Card-Messung. Navigationszustände werden ebenfalls pro Frame gelesen
und anschließend geschrieben. Unveränderte Titel-/Metadaten behalten ihre DOM-Knoten;
der Browser-Test prüft Card-Identität, Metadaten-Identität und Tastaturfokus beim Refresh.
Leere/skelettierte Rails benötigen keine Offscreen-/Resize-Observer.

Ausgeblendete Ansichten dürfen keine gemeldete Scrollposition 0 als Nutzerposition
speichern. Ein zusätzlicher Touch-Test aktualisiert den echten Home-Presenter im
ausgeblendeten Tab und prüft danach denselben Anker. Für breite Viewports wird eine
logisch äquivalente Position vor dem Schreiben in den tatsächlich scrollbaren Bereich
gebracht; Browser-Clamping darf keinen Titel abschneiden.

## Unabhängige gepaarte Linux-CI-Messung

Quality-Run [36302825485](https://github.com/TimeLance89/RoyalDownloader/actions/runs/36302825485),
Frontend-Stand `bbf3491`, drei Samples pro Profil auf demselben Runner.
Baseline `d3aada9`; die späteren Anker-Randfallkorrekturen sind in dieser Kontrollmessung
noch nicht enthalten. Aktueller exakter PR-Stand wird bei jedem Push erneut gepaart geprüft.

| Profil | Render ms vorher → nachher | Long Tasks vorher → nachher | TBT ms vorher → nachher | Layout ms vorher → nachher |
|---|---:|---:|---:|---:|
| Desktop | 53,0 → 36,7 | 2 → 2 | 49 → 31 | 25,6 → 18,7 |
| Desktop 4× | 208,3 → 137,4 | 10 → 7 | 529 → 386 | 99,7 → 69,2 |
| Desktop 6× | 305,1 → 218,0 | 15 → 12 | 1092 → 860 | 147,2 → 105,7 |
| Mobile 4× | 196,2 → 122,2 | 6 → 6 | 497 → 308 | 79,5 → 56,1 |

[CI-Baseline](performance/ci-baseline.json), [CI-Ergebnis](performance/ci-current.json).
Die Long-Task-Anzahl sinkt in den gedrosselten Desktop-Profilen, nicht in jedem
Profil. TBT sinkt in allen vier Profilen. Keine pauschale Behauptung, dass jede
Kennzahl auf jedem Host besser wird. Insbesondere war die mobile Baseline-Interaktion
durch den Scrim blockiert; ihr Event-Timing-Wert ist kein sinnvoller schnellerer
Referenzwert für ein tatsächlich funktionierendes Carousel.

## Dauerhafte Gates und Abdeckung

- 146 Frontend-Unit-/Contract-Tests, 16 Python-Architekturtests lokal grün.
- Chromium: drei mobile Viewports, echte Touch-Pointer und DPR 3, beide Swipe-
  Richtungen, schnelle Swipes, Settle, beide Schleifenränder, vertikales Panning,
  Detail-Tap, keine Swipe-Klicks, gleiche Dokument-History, Tabwechsel samt
  Hintergrund-Refresh, Portrait/Landscape und identischer logischer Anker.
  [Touch-Protokoll](performance/mobile-result.json). Derselbe Test besteht ohne scrollend.
- WebKit: drei mobile Viewports/DPR 3, echte Touch-Taps sowie Scroll-/Resize-Verträge.
  Kein Claim über kontinuierliche native Safari-Momentum-Gesten auf echten iPhones.
- Desktop-Smoke einschließlich 100 logischer Cards, Node-/Fokuserhalt, Queue,
  WebSocket-Reconnect und Feature-Lifecycle; Setup-/Login-Smoke; eingefrorene
  CSS-Äquivalenz (je 2398 Elemente auf Desktop/Mobile); 21 gefüllte Rail-Vergleiche.
  [Visuelles Protokoll](performance/visual-result.json).
- [Finaler Offscreen-Test](performance/offscreen-result.json): acht entfernte Rails
  werden tatsächlich skipped, 0 statt 40 Layouts bei stabiler Dokumenthöhe.
- `verify` verlangt alle Frontend-Gates und führt zusätzlich den gesamten Python-,
  Security-, Container-, E2E- sowie Upgrade-/Rollback-Testlauf durch. CodeQL bleibt aktiv.
- Jeder PR und Push nach overnight/main prüft Chromium, WebKit und den gepaarten
  Performance-Benchmark. Der Release-Workflow verlangt denselben Quality-Lauf.
  Ein zusätzlicher Nightly-Workflow liegt vor; GitHub aktiviert Schedules erst,
  wenn die Workflowdatei auf dem Default-Branch liegt. Bis dahin sind die PR-/Push-
  und Release-Gates bereits verbindlich.

Freigabe und exakter Prüfstand: [PR #364](https://github.com/TimeLance89/RoyalDownloader/pull/364).
Keine Änderungen an persönlichen Requests, Queue-Persistenz, Core-Transport,
WebSocket-Besitz, Framework oder Build-Pipeline.
