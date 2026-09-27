# Frontend Performance Baseline

Baseline: `d3aada9099703c0b9d9b6201f49082c52ddff0d7` (overnight, 2026-09-27).
Vor der ersten Optimierung aufgenommen. Native Chromium 151.0.7922.34 auf Windows,
Playwright 1.62.1; drei unabhängige Browserstarts je Profil, Tabelle zeigt Mediane.
CPU-Drosselung über CDP, Desktop 1440×1000 / DPR 1, Mobile 390×844 / DPR 3 mit Touch.
Kein künstlicher Netzwerk-Throttle; ausschließlich lokale deterministische Fixtures.

## Verfahren und Grenzen

`tests/frontend/performance-fixture.cjs` lädt die echte Anwendung, ihre Module,
Styles und dekorierten Home-Cards. Sieben vorhandene Standard-Rails erhalten
7 Spotlight-, 10 Ranking- und je 16 reguläre Titel: **97 logische Rail-Einträge**.
Die Daten sind in allen Phasen identisch. Die restlichen Rails bleiben verfügbar.
Hero und Hintergrund-Katalognachladen werden nach dem Start im Fixture angehalten,
damit spätere Datenantworten den untersuchten Katalog nicht austauschen.
Das ist ein reproduzierbarer Komponenten-/Integrationsbenchmark, kein NAS-Feldtest.

Initial Render misst die synchrone Erstellung der Rails. Layout-/Script-Zeiten
umfassen Aufbau, Scrollen in die Serien-Rail und eine Interaktion bis zum Settle.
Long Tasks, TBT (Summe max(Dauer−50 ms, 0)) und LCP umfassen den Seitenstart.
Event-Timing-Maximum ist eine INP-nahe Laborgröße, **kein Feld-INP**.
`gestureWallMs` enthält bewusst auch Eingabedauer und Playwright-Latenz; sie ist
nicht als reine UI-Latenz zu interpretieren. Heap ist eine Momentaufnahme ohne GC-Garantie.
Lokale SVG-Fixtures isolieren Layout/DOM von Internet und Bildinhalt; gemessene
Image-Decode-Zeit 0 erlaubt **keine Aussage über reale JPEG-Decodierung**.
Google-Font-Antworten sind für reproduzierbare Offline-Läufe leer; visuelle Vergleiche
verwenden in beiden Ständen denselben Fontzustand. Kein Claim über reale Google-Ladelatenz.

| Profil | Viewport | DOM | volle/logische Cards | Initial ms | Long Tasks | TBT ms | LCP ms | Event max ms | Layout ms | Script ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| desktop | 1440×1000 | 6320 | 257 / 97 | 85.8 | 4 | 137 | 3132 | 64 | 41.4 | 49.5 |
| desktop-4x | 1440×1000 | 6320 | 257 / 97 | 442 | 8 | 1203 | 4320 | 112 | 212.0 | 187.4 |
| desktop-6x | 1440×1000 | 6320 | 257 / 97 | 751.1 | 15 | 2169 | 5768 | 168 | 356.9 | 303.8 |
| mobile-4x | 390×844 | 6320 | 257 / 97 | 437.6 | 6 | 1010 | 4060 | 32 | 191.4 | 157.6 |

Vollständige Einzelmessungen einschließlich Layout-/Style-Anzahl, Style-Zeit,
Script-Evaluation, Heap und Browser in [performance/baseline.json](performance/baseline.json).

## Reproduzierter Mobile-Fehler

Bei 390×844, 430×932 und 768×1024 ändern echte CDP-Touch-Swipes die Rail-Position
nicht. Auch echte Taps öffnen keine Details. `elementFromPoint` identifiziert
`.nav-menu-scrim` als Ziel: Das HTML setzt `hidden`, die mobile CSS-Regel überschreibt
es durch `display:block`. Das Menü ist geschlossen, der Scrim liegt trotzdem über
allen Rails. Rohdaten: [performance/mobile-baseline.json](performance/mobile-baseline.json).
Vertikales Dokument-Scrolling funktioniert weiterhin.

Unabhängiger zweiter Befund: Carousel normalisiert bei jedem `scroll` sowie beim
`pointerdown`, ohne den Pointer-Typ zu unterscheiden. Nach Entfernung des Scrim-
Blockers muss ein separater Test JS-Positionsschreibzugriffe während Touch ausschließen.

## Technisches Audit und Reihenfolge

- 5 reguläre Rails × 16 Titel × 3 Kopien plus 17 Spotlight-/Ranking-Cards = 257 volle Cards.
- `rail-renderer.js` liest die Position jeder Card und startet dazwischen Artwork;
  dadurch folgen Layout Reads und Style-/Image-Writes unmittelbar aufeinander.
- `carousel.js` misst Zyklus, Scrollweite und Navigation mehrmals je Scroll-Ereignis.
- Artwork verwendet IntersectionObserver und `480px 520px` Vorlauf. Zunächst erhalten;
  weniger Duplikate sparen bereits Bild-/Observer-Arbeit ohne riskante Lade-Lücken.
- Hero stoppt Rotation bereits bei `visibilitychange` und `document.hidden`; erhalten.
- Vier Google-Familien, `display=swap`; CSS enthält auch Zwischengewichte. Keine
  Familien/Gewichte blind entfernen oder synthetische Typografie als Optimierung verkaufen.
- Blur/Schatten bleiben unverändert. Zunächst DOM- und Offscreen-Kosten reduzieren;
  ohne isolierten visuellen Nachweis keine pauschale Effektabschwächung.

B: Hidden-Scrim korrigieren; Touch/Momentum ausschließlich beim Settle normalisieren.
C: Kleine, viewportabhängige Randkopien statt drei Vollkopien. Alle Original-Cards
bleiben zugänglich, keine Virtualisierungs-Proxies nötig. Zusammen müssen die beiden
Ränder mindestens einen Viewport plus Reserve abdecken, damit identische sichtbare
Sequenzen beim Wrap existieren. Das ist einfacher und robuster als vollständiges
Recycling mit Fokus-/Listener-/Artwork-Neubindung.
D/E: Offscreen-Rails aus Paint/Layout nehmen und Messungen/Schreibzugriffe bündeln.
F/G/H: Effekte, Fonts und Artwork nur bei nachweisbarem Zusatznutzen ändern;
optionale Qualitätsmodi sind kein Selbstzweck.
I: Touch-/Resize-/Lifecycle-Gates und vergleichender Benchmark auf derselben CI-Maschine.

DOM-Ziel aus der Baseline: mindestens **40 % weniger volle Cards**, unverändert
97 logische Einträge. Zeitbudgets werden anhand mehrfacher A/B-Messungen gewählt,
nicht anhand einer einzelnen Host-abhängigen Millisekundenzahl.
