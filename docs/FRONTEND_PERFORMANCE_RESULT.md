# Frontend Performance – Messprotokoll

Ausgangspunkt und Messgrenzen: [Baseline](FRONTEND_PERFORMANCE_BASELINE.md).
Die Arbeit ist noch nicht abgeschlossen; folgende Abschnitte dokumentieren geprüfte Zwischenschritte.

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
